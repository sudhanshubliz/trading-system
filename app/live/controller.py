from __future__ import annotations

import hashlib
import inspect
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.config.settings import Settings, get_settings
from app.core.logging import log_structured_event
from app.db.models import SystemState
from app.db.session import SessionLocal
from app.execution.live_adapter import BinanceLiveExecutionAdapter, LiveAdapterError
from app.execution.types import Position, Trade
from app.live.guardrails import (
    check_consecutive_losses,
    check_loss_limit,
    check_open_position_limit,
    check_open_risk_limit,
    normalize_order_side,
    safe_float,
    validate_market_freshness,
    validate_order_request,
)
from app.live.locks import LiveLockManager
from app.live.types import (
    LiveExecutionDecision,
    LiveExecutionResult,
    LiveLockType,
    LiveOrderRequest,
    LiveStatus,
)
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.risk_repo import RiskRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.risk.types import RiskAssessment

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveController:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        adapter: BinanceLiveExecutionAdapter | None = None,
        lock_manager: LiveLockManager,
        risk_repo: RiskRepository,
        approvals_repo: ApprovalsRepository,
        trades_repo: TradesRepository,
        positions_repo: PositionsRepository,
        events_repo: EventsRepository | None = None,
        market_data_service: object | None = None,
        execution_service: object | None = None,
        reconciler: object | None = None,
        rollout_service: object | None = None,
        portfolio_service: object | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.adapter = adapter or BinanceLiveExecutionAdapter(self.settings)
        self.lock_manager = lock_manager
        self.risk_repo = risk_repo
        self.approvals_repo = approvals_repo
        self.trades_repo = trades_repo
        self.positions_repo = positions_repo
        self.events_repo = events_repo
        self.market_data_service = market_data_service
        self.execution_service = execution_service
        self.reconciler_service = reconciler
        self.rollout_service = rollout_service
        self.portfolio_service = portfolio_service
        self._recover_armed_state()

    async def arm_live_trading(self) -> LiveStatus:
        if not self.settings.enable_live_trading:
            self.lock_manager.activate_lock(
                LiveLockType.LIVE_NOT_ARMED,
                reason="live_trading_disabled",
            )
            self._set_armed_state(False, reason="live_trading_disabled")
            self._append_ops_event("live_trading_arm_rejected", payload={"reason": "live_trading_disabled"})
            return await self.get_live_status()
        self._set_armed_state(True)
        self._clear_lock_by_type(LiveLockType.MANUAL_LIVE_DISARM)
        self._clear_lock_by_type(LiveLockType.LIVE_NOT_ARMED)
        self._append_ops_event("live_trading_armed", payload={"armed": True})
        return await self.get_live_status()

    async def disarm_live_trading(self) -> LiveStatus:
        self._set_armed_state(False, reason="manual_disarm")
        self.lock_manager.activate_lock(LiveLockType.MANUAL_LIVE_DISARM, reason="manual_disarm")
        self.lock_manager.activate_lock(LiveLockType.LIVE_NOT_ARMED, reason="manual_disarm")
        self._append_ops_event("live_trading_disarmed", payload={"armed": False, "reason": "manual_disarm"})
        return await self.get_live_status()

    async def can_execute_live(self, assessment_id: str) -> LiveExecutionDecision:
        reasons: list[str] = []
        self._sync_runtime_locks()
        self._clear_lock_by_type(LiveLockType.ORDER_VALIDATION_FAILED)
        allowed, active_locks = self.lock_manager.is_live_execution_allowed()
        if not self.settings.enable_live_trading:
            reasons.append("live_trading_disabled")
        if not self._is_armed():
            reasons.append("live_trading_not_armed")
        if not allowed:
            reasons.extend(lock.reason for lock in active_locks if lock.is_active)

        assessment = self.risk_repo.get_assessment(assessment_id)
        if assessment is None:
            reasons.append("assessment_not_found")
            return LiveExecutionDecision(allowed=False, reasons=reasons, active_locks=active_locks)
        if assessment.final_decision != "approved_for_review":
            reasons.append("assessment_not_approved_for_review")

        if self.settings.live_require_explicit_approval:
            approval = self.approvals_repo.find_by_assessment_id(assessment_id)
            if approval is None or approval.status not in {"approved", "executed"}:
                reasons.append("explicit_approval_required")
                self.lock_manager.activate_lock(LiveLockType.APPROVAL_REQUIRED, reason="explicit_approval_required")
            else:
                self._clear_lock_by_type(LiveLockType.APPROVAL_REQUIRED)
        else:
            self._clear_lock_by_type(LiveLockType.APPROVAL_REQUIRED)

        order_request = self._build_order_request(assessment)
        current_snapshot = await self._get_market_snapshot(order_request.symbol)
        failures = validate_order_request(
            symbol=order_request.symbol,
            side=order_request.side,
            quantity=order_request.quantity,
            order_type=order_request.order_type,
            notional=order_request.notional,
            max_order_notional=self.settings.live_max_order_notional,
            limit_price=order_request.limit_price,
            allow_market_orders=self.settings.live_allow_market_orders,
            allow_limit_orders=self.settings.live_allow_limit_orders,
        )
        for lock_type, failure_reason in failures:
            self.lock_manager.activate_lock(lock_type, reason=failure_reason)
            reasons.append(failure_reason)

        if current_snapshot is None:
            self.lock_manager.activate_lock(LiveLockType.MARKET_DATA_STALE, reason="market_data_missing")
            reasons.append("market_data_missing")
        else:
            age_seconds = self._snapshot_age_seconds(current_snapshot)
            is_fresh, freshness_reason = validate_market_freshness(
                age_seconds=age_seconds,
                stale_threshold_seconds=self.settings.live_stale_data_block_sec,
            )
            if not is_fresh and freshness_reason is not None:
                self.lock_manager.activate_lock(LiveLockType.MARKET_DATA_STALE, reason=freshness_reason)
                reasons.append(freshness_reason)
            else:
                self._clear_lock_by_type(LiveLockType.MARKET_DATA_STALE)
                self._validate_slippage_guard(order_request, current_snapshot, reasons)

        self._apply_risk_locks(reasons)
        rollout_decision = await self._evaluate_rollout_policy(assessment, order_request)
        if not rollout_decision.allowed:
            reason = rollout_decision.reasons[0] if rollout_decision.reasons else "rollout_policy_blocked"
            self.lock_manager.activate_lock(
                LiveLockType.ROLLOUT_POLICY_BLOCKED,
                reason=reason,
                metadata={
                    "phase": rollout_decision.current_phase,
                    "capital_limit": rollout_decision.current_capital_limit,
                },
            )
            reasons.extend(rollout_decision.reasons)
        else:
            self._clear_lock_by_type(LiveLockType.ROLLOUT_POLICY_BLOCKED)
        portfolio_decision = await self._evaluate_portfolio_policy(assessment, order_request)
        if not portfolio_decision.allowed:
            reason = portfolio_decision.reasons[0] if portfolio_decision.reasons else "portfolio_policy_blocked"
            self.lock_manager.activate_lock(
                LiveLockType.PORTFOLIO_POLICY_BLOCKED,
                reason=reason,
                metadata={
                    "allocated_capital": portfolio_decision.allocated_capital,
                    "requested_capital": portfolio_decision.requested_capital,
                },
            )
            reasons.extend(portfolio_decision.reasons)
        else:
            self._clear_lock_by_type(LiveLockType.PORTFOLIO_POLICY_BLOCKED)
        return LiveExecutionDecision(
            allowed=len(reasons) == 0,
            reasons=sorted(set(reasons)),
            active_locks=self.lock_manager.list_active_locks(),
            order_request=order_request,
        )

    async def execute_live_trade(self, assessment_id: str) -> LiveExecutionResult:
        decision = await self.can_execute_live(assessment_id)
        if not decision.allowed or decision.order_request is None:
            self._append_event(
                "live_order_rejected",
                assessment_id=assessment_id,
                payload={"reasons": decision.reasons},
            )
            return LiveExecutionResult(
                allowed=False,
                reasons=decision.reasons,
                trade_id=None,
                position_id=None,
                client_order_id=decision.order_request.client_order_id if decision.order_request else None,
                exchange_order_id=None,
                status="blocked",
                active_locks=decision.active_locks,
            )

        assessment = self.risk_repo.get_assessment(assessment_id)
        assert assessment is not None
        existing_trade = self.trades_repo.get_trade_by_client_order_id(decision.order_request.client_order_id)
        if existing_trade is not None and existing_trade.status not in {"FAILED", "REJECTED"}:
            return LiveExecutionResult(
                allowed=True,
                reasons=[],
                trade_id=existing_trade.trade_id,
                position_id=existing_trade.position_id,
                client_order_id=existing_trade.client_order_id,
                exchange_order_id=existing_trade.exchange_order_id,
                status=existing_trade.status,
                active_locks=self.lock_manager.list_active_locks(),
            )

        trade = self._build_live_trade(assessment, decision.order_request)
        position = self._build_live_position(trade, assessment)
        self.trades_repo.upsert_trade(trade)
        self.positions_repo.upsert_position(position)
        self._append_event(
            "live_order_requested",
            assessment_id=assessment_id,
            trade_id=trade.trade_id,
            payload={"client_order_id": trade.client_order_id},
        )

        try:
            order_result = self.adapter.place_order(
                decision.order_request,
                snapshot=await self._get_market_snapshot(decision.order_request.symbol),
            )
        except LiveAdapterError as exc:
            failed_trade = replace(
                trade,
                status="FAILED",
                exchange_status="FAILED",
                failure_reason=str(exc),
            )
            self.trades_repo.upsert_trade(failed_trade)
            self.lock_manager.activate_lock(LiveLockType.ORDER_VALIDATION_FAILED, reason=str(exc))
            self._append_event(
                "live_order_rejected",
                assessment_id=assessment_id,
                trade_id=trade.trade_id,
                payload={"reason": str(exc)},
            )
            return LiveExecutionResult(
                allowed=False,
                reasons=[str(exc)],
                trade_id=failed_trade.trade_id,
                position_id=position.position_id,
                client_order_id=failed_trade.client_order_id,
                exchange_order_id=None,
                status="FAILED",
                active_locks=self.lock_manager.list_active_locks(),
            )

        final_trade = replace(
            trade,
            status=self._map_exchange_status(order_result.status),
            exchange_order_id=order_result.exchange_order_id,
            exchange_status=order_result.status,
        )
        final_position = replace(
            position,
            current_price=order_result.executed_price or position.current_price,
        )
        self.trades_repo.upsert_trade(final_trade)
        self.positions_repo.upsert_position(final_position)
        if self.rollout_service is not None and hasattr(self.rollout_service, "apply_post_trade_rollout_update"):
            self.rollout_service.apply_post_trade_rollout_update()
        self._append_event(
            "live_order_submitted",
            assessment_id=assessment_id,
            trade_id=final_trade.trade_id,
            payload={
                "client_order_id": order_result.client_order_id,
                "exchange_order_id": order_result.exchange_order_id,
                "status": order_result.status,
            },
        )
        return LiveExecutionResult(
            allowed=True,
            reasons=[],
            trade_id=final_trade.trade_id,
            position_id=final_position.position_id,
            client_order_id=order_result.client_order_id,
            exchange_order_id=order_result.exchange_order_id,
            status=final_trade.status,
            active_locks=self.lock_manager.list_active_locks(),
        )

    async def get_live_status(self) -> LiveStatus:
        self._sync_runtime_locks()
        active_locks = self.lock_manager.list_active_locks()
        daily_pnl, weekly_pnl, consecutive_losses = self._calculate_live_loss_stats()
        open_positions = self.positions_repo.list_open_positions("live")
        can_execute = self.settings.enable_live_trading and self._is_armed() and len(active_locks) == 0
        return LiveStatus(
            enabled=self.settings.enable_live_trading,
            armed=self._is_armed(),
            execution_mode="live",
            can_execute=can_execute,
            global_pause=self._is_global_pause(),
            active_locks=active_locks,
            stale_market_data=any(lock.lock_type == LiveLockType.MARKET_DATA_STALE for lock in active_locks),
            open_live_positions=len(open_positions),
            daily_live_pnl=daily_pnl,
            weekly_live_pnl=weekly_pnl,
            timestamp=utc_now(),
        )

    async def clear_lock(self, lock_id: str) -> LiveStatus:
        self.lock_manager.clear_lock(lock_id, reason="manual_clear")
        return await self.get_live_status()

    def list_locks(self) -> list:
        self._sync_runtime_locks()
        return self.lock_manager.list_locks()

    async def reconcile(self):
        if self.reconciler_service is None:
            from app.live.types import LiveReconciliationResult

            return LiveReconciliationResult(ok=True, mismatches=[], activated_lock_id=None, timestamp=utc_now())
        return self.reconciler_service.reconcile()

    def _build_order_request(self, assessment: RiskAssessment) -> LiveOrderRequest:
        trade_plan = assessment.generated_trade_plan
        entry_price = safe_float(trade_plan.get("entry_price"))
        quantity = safe_float(trade_plan.get("position_size"))
        notional = safe_float(entry_price * quantity)
        order_type = "LIMIT" if self.settings.live_allow_limit_orders else "MARKET"
        return LiveOrderRequest(
            assessment_id=assessment.assessment_id,
            symbol=assessment.symbol,
            side=normalize_order_side(assessment.side),
            quantity=quantity,
            order_type=order_type,
            limit_price=entry_price if order_type == "LIMIT" else None,
            stop_loss=safe_float(trade_plan.get("stop_loss")),
            notional=notional,
            client_order_id=self._build_client_order_id(assessment.assessment_id),
        )

    def _build_live_trade(self, assessment: RiskAssessment, order_request: LiveOrderRequest) -> Trade:
        now = utc_now()
        digest = hashlib.sha1(order_request.client_order_id.encode("utf-8")).hexdigest()
        trade_id = f"trd_live_{digest[:12]}"
        position_id = f"pos_live_{digest[:12]}"
        trade = Trade(
            trade_id=trade_id,
            approval_id=self._approval_id_for_assessment(assessment.assessment_id),
            assessment_id=assessment.assessment_id,
            signal_id=assessment.signal_id,
            position_id=position_id,
            symbol=assessment.symbol,
            side=assessment.side,
            strategy_name=assessment.strategy_name,
            quantity=order_request.quantity,
            execution_price=order_request.limit_price or 0.0,
            requested_entry_price=order_request.limit_price or 0.0,
            stop_loss=safe_float(assessment.generated_trade_plan.get("stop_loss")),
            target_1=safe_float(assessment.generated_trade_plan.get("target_1")),
            target_2=safe_float(assessment.generated_trade_plan.get("target_2")),
            status="EXECUTION_REQUESTED",
            execution_mode="live",
            opened_at=now,
            updated_at=now,
            client_order_id=order_request.client_order_id,
            exchange_order_id=None,
            exchange_status="PENDING",
            reconciliation_status="pending",
            last_reconciled_at=None,
            failure_reason=None,
        )
        return trade

    def _build_live_position(self, trade: Trade, assessment: RiskAssessment) -> Position:
        now = utc_now()
        return Position(
            position_id=trade.position_id,
            trade_id=trade.trade_id,
            approval_id=trade.approval_id,
            assessment_id=assessment.assessment_id,
            signal_id=assessment.signal_id,
            symbol=assessment.symbol,
            side=assessment.side,
            strategy_name=assessment.strategy_name,
            initial_quantity=trade.quantity,
            quantity_open=trade.quantity,
            entry_price=trade.requested_entry_price,
            current_price=trade.requested_entry_price,
            stop_loss=trade.stop_loss,
            target_1=trade.target_1,
            target_2=trade.target_2,
            status="open",
            opened_at=now,
            updated_at=now,
            execution_mode="live",
            reconciliation_status="pending",
            last_reconciled_at=None,
        )

    def _approval_id_for_assessment(self, assessment_id: str) -> str:
        approval = self.approvals_repo.find_by_assessment_id(assessment_id)
        return approval.approval_id if approval is not None else f"live_{assessment_id}"

    def _build_client_order_id(self, assessment_id: str) -> str:
        digest = hashlib.sha1(assessment_id.encode("utf-8")).hexdigest()
        return f"live_{digest[:20]}"

    def _append_event(
        self,
        event_type: str,
        *,
        assessment_id: str,
        trade_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type=event_type,
                entity_id=assessment_id,
                trade_id=trade_id,
                execution_mode="live",
                payload=payload or {},
            )
        log_structured_event(
            logger,
            event_type,
            assessment_id=assessment_id,
            trade_id=trade_id,
            payload=payload or {},
        )

    def _append_ops_event(self, event_type: str, *, payload: dict[str, Any]) -> None:
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type=event_type,
                entity_id="live_control",
                execution_mode="live",
                payload=payload,
            )
        log_structured_event(logger, event_type, payload=payload)

    def _recover_armed_state(self) -> None:
        with SessionLocal() as session:
            state = session.get(SystemState, "live_trading")
            if state is None:
                session.add(
                    SystemState(
                        key="live_trading",
                        value_json=json.dumps({"armed": False}),
                        updated_at=utc_now(),
                    )
                )
                session.commit()
                self.lock_manager.activate_lock(LiveLockType.LIVE_NOT_ARMED, reason="default_disarmed")
                return
            payload = json.loads(state.value_json)
            should_restore = bool(payload.get("armed", False)) and self.settings.enable_live_trading
            if should_restore and len(self.lock_manager.list_active_locks()) == 0:
                self._set_armed_state(True)
                self._clear_lock_by_type(LiveLockType.LIVE_NOT_ARMED)
                return
            self._set_armed_state(False, reason="startup_safety_restore_disarmed")
            self.lock_manager.activate_lock(LiveLockType.LIVE_NOT_ARMED, reason="startup_safety_restore_disarmed")

    def _set_armed_state(self, armed: bool, reason: str | None = None) -> None:
        with SessionLocal() as session:
            state = session.get(SystemState, "live_trading")
            if state is None:
                state = SystemState(
                    key="live_trading",
                    value_json=json.dumps({"armed": armed, "reason": reason}),
                    updated_at=utc_now(),
                )
                session.add(state)
            else:
                state.value_json = json.dumps({"armed": armed, "reason": reason})
                state.updated_at = utc_now()
            session.commit()

    def _is_armed(self) -> bool:
        with SessionLocal() as session:
            state = session.get(SystemState, "live_trading")
            if state is None:
                return False
            payload = json.loads(state.value_json)
            return bool(payload.get("armed", False))

    def _is_global_pause(self) -> bool:
        if self.execution_service is not None and hasattr(self.execution_service, "is_paused"):
            return bool(self.execution_service.is_paused())
        with SessionLocal() as session:
            state = session.get(SystemState, "global_pause")
            if state is None:
                return False
            payload = json.loads(state.value_json)
            return bool(payload.get("paused", False))

    def _sync_runtime_locks(self) -> None:
        if self._is_global_pause():
            self.lock_manager.activate_lock(LiveLockType.GLOBAL_PAUSE, reason="global_pause_active")
        else:
            self._clear_lock_by_type(LiveLockType.GLOBAL_PAUSE)

        if not self._is_armed():
            self.lock_manager.activate_lock(LiveLockType.LIVE_NOT_ARMED, reason="live_not_armed")
        else:
            self._clear_lock_by_type(LiveLockType.LIVE_NOT_ARMED)

    def _clear_lock_by_type(self, lock_type: str) -> None:
        lock_id = self.lock_manager._build_lock_id(lock_type)
        self.lock_manager.clear_lock(lock_id, reason="condition_cleared")

    async def _evaluate_rollout_policy(self, assessment: RiskAssessment, order_request: LiveOrderRequest):
        if self.rollout_service is None or not hasattr(self.rollout_service, "evaluate_trade_under_rollout"):
            from app.live.types import RolloutDecision

            return RolloutDecision(
                allowed=True,
                current_phase="scaled",
                current_capital_limit=order_request.notional,
                allowed_capital_limit=order_request.notional,
                deployed_capital=0.0,
                remaining_capital=order_request.notional,
                strategy_allocations={},
                symbol_allocations={},
                rollback_active=False,
                reasons=[],
            )
        decision = self.rollout_service.evaluate_trade_under_rollout(
            order_request=order_request,
            assessment=assessment,
        )
        if getattr(decision, "rollback_active", False) and getattr(decision, "current_phase", "") == "disabled":
            self._handle_critical_rollout_rollback(decision)
        return decision

    async def _evaluate_portfolio_policy(self, assessment: RiskAssessment, order_request: LiveOrderRequest):
        if self.portfolio_service is None or not hasattr(self.portfolio_service, "evaluate_live_candidate"):
            from app.portfolio.types import PortfolioDecision

            return PortfolioDecision(
                assessment_id=assessment.assessment_id,
                symbol=assessment.symbol,
                strategy_name=assessment.strategy_name,
                side=assessment.side,
                allowed=True,
                decision="approved",
                allocated_capital=order_request.notional,
                allocated_quantity=order_request.quantity,
                requested_capital=order_request.notional,
                score=0.0,
                ranking_index=0,
                reasons=[],
                cluster_name=None,
                execution_mode="live",
                timestamp=utc_now(),
            )
        return self.portfolio_service.evaluate_live_candidate(assessment, order_request)

    def _handle_critical_rollout_rollback(self, decision) -> None:
        if not self.settings.live_auto_disarm_on_critical_rollback:
            return
        self._set_armed_state(False, reason="critical_rollout_rollback")
        self.lock_manager.activate_lock(
            LiveLockType.LIVE_NOT_ARMED,
            reason="critical_rollout_rollback",
        )
        self._append_ops_event(
            "live_trading_auto_disarmed",
            payload={
                "reason": "critical_rollout_rollback",
                "rollout_phase": getattr(decision, "current_phase", "disabled"),
                "reasons": getattr(decision, "reasons", []),
            },
        )

    async def _get_market_snapshot(self, symbol: str):
        market_data_service = self.market_data_service
        if market_data_service is None:
            return None
        get_snapshot = getattr(market_data_service, "get_snapshot", None)
        if get_snapshot is None:
            return None
        snapshot = get_snapshot(symbol)
        if inspect.isawaitable(snapshot):
            snapshot = await snapshot
        return snapshot

    def _snapshot_age_seconds(self, snapshot: Any) -> float | None:
        if isinstance(snapshot, dict):
            ts = snapshot.get("snapshot_time") or snapshot.get("ticker_updated_at")
        else:
            ts = getattr(snapshot, "snapshot_time", None) or getattr(snapshot, "ticker_updated_at", None)
        if ts is None:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max((utc_now() - ts.astimezone(timezone.utc)).total_seconds(), 0.0)

    def _validate_slippage_guard(self, order_request: LiveOrderRequest, snapshot: Any, reasons: list[str]) -> None:
        if snapshot is None or order_request.limit_price is None:
            return
        if isinstance(snapshot, dict):
            last_price = snapshot.get("last_price")
        else:
            last_price = getattr(snapshot, "last_price", None)
        if last_price is None or float(last_price) <= 0:
            return
        slippage_pct = abs(float(last_price) - order_request.limit_price) / float(last_price) * 100.0
        if slippage_pct > self.settings.live_slippage_guard_pct:
            self.lock_manager.activate_lock(
                LiveLockType.ORDER_VALIDATION_FAILED,
                reason="slippage_guard_exceeded",
                metadata={"slippage_pct": round(slippage_pct, 4)},
            )
            reasons.append("slippage_guard_exceeded")

    def _calculate_live_loss_stats(self) -> tuple[float, float, int]:
        trades = self.trades_repo.list_trades("live")
        now = utc_now()
        daily = 0.0
        weekly = 0.0
        consecutive_losses = 0
        recent = sorted(trades, key=lambda item: item.updated_at, reverse=True)
        for trade in recent:
            if trade.execution_mode != "live":
                continue
            if trade.closed_at is not None and trade.closed_at.date() == now.date():
                daily += trade.realized_pnl
            if trade.closed_at is not None:
                iso_year, iso_week, _ = trade.closed_at.isocalendar()
                now_year, now_week, _ = now.isocalendar()
                if (iso_year, iso_week) == (now_year, now_week):
                    weekly += trade.realized_pnl
            if trade.realized_pnl < 0:
                consecutive_losses += 1
            elif trade.realized_pnl > 0:
                break
        return round(daily, 4), round(weekly, 4), consecutive_losses

    def _apply_risk_locks(self, reasons: list[str]) -> None:
        daily_pnl, weekly_pnl, consecutive_losses = self._calculate_live_loss_stats()
        starting_balance = self.settings.paper_account_start_balance or 1.0
        daily_loss_pct = abs(min(daily_pnl, 0.0)) / starting_balance * 100.0
        weekly_loss_pct = abs(min(weekly_pnl, 0.0)) / starting_balance * 100.0
        open_positions = self.positions_repo.list_open_positions("live")
        open_risk_amount = sum(
            abs(position.entry_price - position.stop_loss) * position.quantity_open for position in open_positions
        )
        open_risk_pct = open_risk_amount / starting_balance * 100.0 if starting_balance > 0 else 0.0

        if check_loss_limit(pnl_pct=-daily_loss_pct, max_loss_pct=self.settings.live_max_daily_loss_pct):
            self.lock_manager.activate_lock(LiveLockType.DAILY_LOSS_LIMIT, reason="daily_loss_limit_reached")
            reasons.append("daily_loss_limit_reached")
        else:
            self._clear_lock_by_type(LiveLockType.DAILY_LOSS_LIMIT)

        if check_loss_limit(pnl_pct=-weekly_loss_pct, max_loss_pct=self.settings.live_max_weekly_loss_pct):
            self.lock_manager.activate_lock(LiveLockType.WEEKLY_LOSS_LIMIT, reason="weekly_loss_limit_reached")
            reasons.append("weekly_loss_limit_reached")
        else:
            self._clear_lock_by_type(LiveLockType.WEEKLY_LOSS_LIMIT)

        if check_consecutive_losses(
            consecutive_losses=consecutive_losses,
            max_consecutive_losses=self.settings.live_max_consecutive_losses,
        ):
            self.lock_manager.activate_lock(LiveLockType.CONSECUTIVE_LOSS_LIMIT, reason="consecutive_loss_limit_reached")
            reasons.append("consecutive_loss_limit_reached")
        else:
            self._clear_lock_by_type(LiveLockType.CONSECUTIVE_LOSS_LIMIT)

        if check_open_position_limit(
            open_positions=len(open_positions),
            max_open_positions=self.settings.live_max_open_positions,
        ):
            self.lock_manager.activate_lock(LiveLockType.OPEN_POSITION_LIMIT, reason="open_position_limit_reached")
            reasons.append("open_position_limit_reached")
        else:
            self._clear_lock_by_type(LiveLockType.OPEN_POSITION_LIMIT)

        if check_open_risk_limit(
            open_risk_pct=open_risk_pct,
            max_open_risk_pct=self.settings.live_max_open_risk_pct,
        ):
            self.lock_manager.activate_lock(LiveLockType.OPEN_RISK_LIMIT, reason="open_risk_limit_reached")
            reasons.append("open_risk_limit_reached")
        else:
            self._clear_lock_by_type(LiveLockType.OPEN_RISK_LIMIT)

    def _map_exchange_status(self, exchange_status: str) -> str:
        normalized = exchange_status.upper()
        mapping = {
            "NEW": "EXECUTED",
            "PARTIALLY_FILLED": "PARTIALLY_FILLED",
            "FILLED": "FILLED",
            "CANCELED": "FAILED",
            "REJECTED": "REJECTED",
            "EXPIRED": "FAILED",
        }
        return mapping.get(normalized, normalized)

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any

from app.config.settings import Settings, get_settings
from app.execution.types import Position, Trade
from app.live.scaling import (
    compute_allocation_state,
    compute_allowed_capital,
    compute_live_performance_metrics,
    can_scale_down,
    can_scale_up,
    get_phase_rule,
    next_phase,
    previous_phase,
    safe_float,
)
from app.live.types import LiveOrderRequest, LiveRolloutState, RolloutDecision
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.rollout_repo import RolloutRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.risk.types import RiskAssessment


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveRolloutPolicy:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        rollout_repo: RolloutRepository | None = None,
        positions_repo: PositionsRepository | None = None,
        trades_repo: TradesRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.rollout_repo = rollout_repo
        self.positions_repo = positions_repo
        self.trades_repo = trades_repo
        self.events_repo = events_repo

    def get_rollout_state(self) -> LiveRolloutState:
        if self.rollout_repo is not None:
            persisted = self.rollout_repo.get_rollout_state()
            if persisted is not None:
                return self._refresh_allocations(persisted)
        state = self._build_default_state()
        self._persist_state(state)
        return state

    def set_rollout_phase(
        self,
        phase: str,
        *,
        changed_by: str = "operator",
        reason: str | None = None,
        allow_scale_validation: bool = True,
    ) -> LiveRolloutState:
        normalized = str(phase).lower()
        if normalized not in self.settings.live_allowed_phases:
            raise ValueError("invalid_rollout_phase")

        current = self.get_rollout_state()
        if normalized == current.current_phase:
            return current

        moving_up = self._phase_rank(normalized) > self._phase_rank(current.current_phase)
        if moving_up and allow_scale_validation:
            allowed, reasons = can_scale_up(
                self.settings,
                current_phase=current.current_phase,
                trades=self._list_live_trades(),
            )
            if not allowed and not (current.current_phase == "disabled" and normalized == "micro"):
                raise ValueError(",".join(reasons))

        updated = LiveRolloutState(
            current_phase=normalized,
            current_capital_limit=compute_allowed_capital(self.settings, normalized),
            allowed_capital_limit=compute_allowed_capital(self.settings, normalized),
            strategy_allocations=current.strategy_allocations,
            symbol_allocations=current.symbol_allocations,
            last_phase_change_at=utc_now(),
            changed_by=changed_by,
            reason=reason or f"phase_changed_to_{normalized}",
            rollback_active=False,
            notes=[*current.notes, f"{utc_now().isoformat()}:{changed_by}:{reason or normalized}"][-20:],
            updated_at=utc_now(),
        )
        updated = self._refresh_allocations(updated)
        self._persist_state(updated)
        self._append_phase_event(
            event_type="rollout_phase_changed",
            state=updated,
            payload={"previous_phase": current.current_phase},
        )
        event_type = None
        if moving_up:
            event_type = "rollout_scale_up"
        elif self._phase_rank(normalized) < self._phase_rank(current.current_phase):
            event_type = "rollout_scale_down"
        if event_type is None:
            return updated
        self._append_phase_event(
            event_type=event_type,
            state=updated,
            payload={"previous_phase": current.current_phase},
        )
        return updated

    def scale_up(self, *, changed_by: str = "operator", reason: str | None = None) -> LiveRolloutState:
        current = self.get_rollout_state()
        target = next_phase(current.current_phase)
        return self.set_rollout_phase(
            target,
            changed_by=changed_by,
            reason=reason or "manual_scale_up",
            allow_scale_validation=True,
        )

    def scale_down(self, *, changed_by: str = "operator", reason: str | None = None) -> LiveRolloutState:
        current = self.get_rollout_state()
        target = previous_phase(current.current_phase)
        updated = self.set_rollout_phase(
            target,
            changed_by=changed_by,
            reason=reason or "manual_scale_down",
            allow_scale_validation=False,
        )
        return updated

    def rollback_live(self, *, changed_by: str = "operator", reason: str | None = None) -> LiveRolloutState:
        current = self.get_rollout_state()
        target = previous_phase(current.current_phase)
        if current.current_phase == "disabled":
            target = "disabled"
        updated = replace(
            self.set_rollout_phase(
                target,
                changed_by=changed_by,
                reason=reason or "manual_rollback",
                allow_scale_validation=False,
            ),
            rollback_active=True,
            reason=reason or "manual_rollback",
            updated_at=utc_now(),
        )
        self._persist_state(updated)
        self._append_phase_event(
            event_type="rollout_manual_rollback",
            state=updated,
            payload={"previous_phase": current.current_phase},
        )
        return updated

    def evaluate_trade_under_rollout(
        self,
        *,
        order_request: LiveOrderRequest,
        assessment: RiskAssessment,
    ) -> RolloutDecision:
        if not self.settings.rollout_policy_enabled:
            open_positions = self._list_open_positions()
            allocation = compute_allocation_state(
                open_positions,
                capital_limit=safe_float(self.settings.live_max_capital_total),
            )
            return RolloutDecision(
                allowed=True,
                current_phase="scaled",
                current_capital_limit=safe_float(self.settings.live_max_capital_total),
                allowed_capital_limit=safe_float(self.settings.live_max_capital_total),
                deployed_capital=allocation.deployed_capital,
                remaining_capital=allocation.remaining_capital,
                strategy_allocations=allocation.strategy_allocations,
                symbol_allocations=allocation.symbol_allocations,
                rollback_active=False,
                reasons=[],
            )

        state = self.run_rollout_guardrails(changed_by="system", reason="pre_trade_guardrails")
        phase_rule = get_phase_rule(self.settings, state.current_phase)
        capital_limit = safe_float(min(state.current_capital_limit, phase_rule.capital_limit))
        open_positions = self._list_open_positions()
        allocation = compute_allocation_state(open_positions, capital_limit=capital_limit)
        reasons: list[str] = []

        if state.current_phase == "disabled":
            reasons.append("rollout_phase_disabled")
        if state.rollback_active:
            reasons.append("rollout_rollback_active")

        portfolio_ok, portfolio_reasons = self._validate_portfolio(
            state=state,
            requested_notional=order_request.notional,
            allocation=allocation,
        )
        if not portfolio_ok:
            reasons.extend(portfolio_reasons)

        strategy_ok, strategy_reason = self._validate_strategy(
            state=state,
            strategy_name=assessment.strategy_name,
            requested_notional=order_request.notional,
            strategy_allocations=allocation.strategy_allocations,
        )
        if not strategy_ok:
            reasons.append(strategy_reason)

        symbol_ok, symbol_reason = self._validate_symbol(
            state=state,
            symbol=order_request.symbol,
            requested_notional=order_request.notional,
            symbol_allocations=allocation.symbol_allocations,
        )
        if not symbol_ok:
            reasons.append(symbol_reason)

        decision = RolloutDecision(
            allowed=len(reasons) == 0,
            current_phase=state.current_phase,
            current_capital_limit=capital_limit,
            allowed_capital_limit=state.allowed_capital_limit,
            deployed_capital=allocation.deployed_capital,
            remaining_capital=allocation.remaining_capital,
            strategy_allocations=allocation.strategy_allocations,
            symbol_allocations=allocation.symbol_allocations,
            rollback_active=state.rollback_active,
            reasons=sorted(set(reasons)),
        )
        event_type = "rollout_trade_allowed" if decision.allowed else "rollout_trade_denied"
        self._append_event(
            event_type,
            payload={
                "assessment_id": assessment.assessment_id,
                "symbol": assessment.symbol,
                "strategy_name": assessment.strategy_name,
                "phase": decision.current_phase,
                "capital_limit": decision.current_capital_limit,
                "deployed_capital": decision.deployed_capital,
                "requested_notional": safe_float(order_request.notional),
                "reasons": decision.reasons,
            },
        )
        return decision

    def apply_post_trade_rollout_update(self) -> LiveRolloutState:
        state = self._refresh_allocations(self.get_rollout_state())
        self._persist_state(state)
        return state

    def run_rollout_guardrails(
        self,
        *,
        changed_by: str = "system",
        reason: str | None = None,
    ) -> LiveRolloutState:
        state = self.get_rollout_state()
        if not self.settings.rollout_policy_enabled or not self.settings.live_auto_deescalate_enabled:
            return state

        should_scale_down, reasons, critical = can_scale_down(
            self.settings,
            trades=self._list_live_trades(),
            manual=False,
        )
        if not should_scale_down or not reasons:
            return state

        target = "disabled" if critical else previous_phase(state.current_phase)
        if state.current_phase == "disabled" and target == "disabled" and state.rollback_active:
            return state

        updated = LiveRolloutState(
            current_phase=target,
            current_capital_limit=compute_allowed_capital(self.settings, target),
            allowed_capital_limit=compute_allowed_capital(self.settings, target),
            strategy_allocations=state.strategy_allocations,
            symbol_allocations=state.symbol_allocations,
            last_phase_change_at=utc_now(),
            changed_by=changed_by,
            reason=reason or ",".join(reasons),
            rollback_active=True,
            notes=[*state.notes, f"{utc_now().isoformat()}:{changed_by}:{','.join(reasons)}"][-20:],
            updated_at=utc_now(),
        )
        updated = self._refresh_allocations(updated)
        self._persist_state(updated)
        self._append_phase_event(
            event_type="rollout_phase_changed",
            state=updated,
            payload={"previous_phase": state.current_phase, "critical": critical, "reasons": reasons},
        )
        self._append_phase_event(
            event_type="rollout_auto_rollback",
            state=updated,
            payload={"previous_phase": state.current_phase, "critical": critical, "reasons": reasons},
        )
        return updated

    def get_capital_status(self) -> dict[str, Any]:
        state = self.get_rollout_state()
        allocation = compute_allocation_state(
            self._list_open_positions(),
            capital_limit=state.current_capital_limit,
        )
        return {
            "current_phase": state.current_phase,
            "current_capital_limit": state.current_capital_limit,
            "allowed_capital_limit": state.allowed_capital_limit,
            "deployed_capital": allocation.deployed_capital,
            "remaining_capital": allocation.remaining_capital,
            "strategy_allocations": allocation.strategy_allocations,
            "symbol_allocations": allocation.symbol_allocations,
            "rollback_active": state.rollback_active,
            "last_phase_change_at": state.last_phase_change_at,
            "changed_by": state.changed_by,
            "reason": state.reason,
            "notes": state.notes,
            "timestamp": utc_now(),
        }

    def list_phase_history(self, *, limit: int | None = None):
        if self.rollout_repo is None:
            return []
        return self.rollout_repo.list_phase_history(
            limit=limit or self.settings.live_rollout_store_limit,
        )

    def _build_default_state(self) -> LiveRolloutState:
        phase = self.settings.live_phase_default if self.settings.live_phase_default in self.settings.live_allowed_phases else "disabled"
        capital_limit = compute_allowed_capital(self.settings, phase)
        return LiveRolloutState(
            current_phase=phase,
            current_capital_limit=capital_limit,
            allowed_capital_limit=capital_limit,
            strategy_allocations={},
            symbol_allocations={},
            last_phase_change_at=utc_now(),
            changed_by="system",
            reason="startup_default",
            rollback_active=False,
            notes=[],
            updated_at=utc_now(),
        )

    def _refresh_allocations(self, state: LiveRolloutState) -> LiveRolloutState:
        allocation = compute_allocation_state(
            self._list_open_positions(),
            capital_limit=state.current_capital_limit,
        )
        return replace(
            state,
            strategy_allocations=allocation.strategy_allocations,
            symbol_allocations=allocation.symbol_allocations,
            updated_at=utc_now(),
        )

    def _persist_state(self, state: LiveRolloutState) -> None:
        if self.rollout_repo is None:
            return
        self.rollout_repo.upsert_rollout_state(state)

    def _append_phase_event(
        self,
        *,
        event_type: str,
        state: LiveRolloutState,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self.rollout_repo is None:
            self._append_event(
                event_type,
                payload={
                    "phase": state.current_phase,
                    "capital_limit": state.current_capital_limit,
                    "changed_by": state.changed_by,
                    "reason": state.reason,
                    "rollback_active": state.rollback_active,
                    **(payload or {}),
                },
            )
            return
        if self.rollout_repo is not None:
            self.rollout_repo.append_phase_change_event(
                event_type=event_type,
                phase=state.current_phase,
                capital_limit=state.current_capital_limit,
                changed_by=state.changed_by,
                reason=state.reason,
                rollback_active=state.rollback_active,
                payload=payload or {},
            )

    def _append_event(self, event_type: str, *, payload: dict[str, Any]) -> None:
        if self.events_repo is None:
            return
        self.events_repo.append_event(
            event_type=event_type,
            entity_id="live_rollout",
            execution_mode="live",
            payload=payload,
        )

    def _phase_rank(self, phase: str) -> int:
        try:
            return ["disabled", "micro", "limited", "scaled"].index(str(phase).lower())
        except ValueError:
            return 0

    def _validate_portfolio(
        self,
        *,
        state: LiveRolloutState,
        requested_notional: float,
        allocation,
    ) -> tuple[bool, list[str]]:
        phase_rule = get_phase_rule(self.settings, state.current_phase)
        phase_rule = replace(phase_rule, capital_limit=state.current_capital_limit)
        allowed = True
        reasons: list[str] = []
        if safe_float(allocation.deployed_capital + requested_notional) > state.current_capital_limit:
            allowed = False
            reasons.append("rollout_capital_limit_exceeded")
            self._append_event(
                "rollout_cap_exceeded",
                payload={
                    "current_phase": state.current_phase,
                    "capital_limit": state.current_capital_limit,
                    "deployed_capital": allocation.deployed_capital,
                    "requested_notional": safe_float(requested_notional),
                },
            )
        max_positions = min(
            max(self.settings.live_portfolio_max_correlated_positions, 0),
            max(phase_rule.max_open_positions, 0),
        )
        if allocation.open_position_count >= max_positions and max_positions >= 0:
            allowed = False
            reasons.append("portfolio_concentration_limit_exceeded")
        return allowed, reasons

    def _validate_strategy(
        self,
        *,
        state: LiveRolloutState,
        strategy_name: str,
        requested_notional: float,
        strategy_allocations: dict[str, float],
    ) -> tuple[bool, str]:
        max_capital = safe_float(state.current_capital_limit * self.settings.live_strategy_max_capital_pct / 100.0)
        projected = safe_float(strategy_allocations.get(strategy_name, 0.0) + requested_notional)
        if projected <= max_capital:
            return True, ""
        self._append_event(
            "rollout_strategy_cap_exceeded",
            payload={
                "strategy_name": strategy_name,
                "projected_capital": projected,
                "max_capital": max_capital,
                "phase": state.current_phase,
            },
        )
        return False, "strategy_cap_exceeded"

    def _validate_symbol(
        self,
        *,
        state: LiveRolloutState,
        symbol: str,
        requested_notional: float,
        symbol_allocations: dict[str, float],
    ) -> tuple[bool, str]:
        max_capital = safe_float(state.current_capital_limit * self.settings.live_symbol_max_capital_pct / 100.0)
        projected = safe_float(symbol_allocations.get(symbol, 0.0) + requested_notional)
        if projected <= max_capital:
            return True, ""
        self._append_event(
            "rollout_symbol_cap_exceeded",
            payload={
                "symbol": symbol,
                "projected_capital": projected,
                "max_capital": max_capital,
                "phase": state.current_phase,
            },
        )
        return False, "symbol_cap_exceeded"

    def _list_open_positions(self) -> list[Position]:
        if self.positions_repo is None:
            return []
        return self.positions_repo.list_open_positions("live")

    def _list_live_trades(self) -> list[Trade]:
        if self.trades_repo is None:
            return []
        return self.trades_repo.list_trades("live")

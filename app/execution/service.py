from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings, get_settings
from app.core.logging import log_structured_event
from app.db.models import SystemState
from app.db.session import SessionLocal
from app.execution.approvals import ApprovalStore
from app.execution.engine import PaperExecutionEngine
from app.execution.pnl import build_pnl_summary
from app.execution.positions import PositionManager
from app.execution.types import Approval, ControlStatus, PnlSummary, Position, Trade
from app.market_data.types import TickerSnapshot
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.risk.types import RiskAssessment

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        risk_service: object | None = None,
        market_data_service: object | None = None,
        time_provider: Callable[[], datetime] | None = None,
        use_persistent_control_state: bool = True,
        execution_mode: str | None = None,
        approvals_repo: ApprovalsRepository | None = None,
        trades_repo: TradesRepository | None = None,
        positions_repo: PositionsRepository | None = None,
        events_repo: EventsRepository | None = None,
        persistence_session_factory: sessionmaker[Session] | None = None,
        live_controller: object | None = None,
        portfolio_service: object | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.risk_service = risk_service
        self.market_data_service = market_data_service
        self.time_provider = time_provider or utc_now
        self.use_persistent_control_state = use_persistent_control_state
        self.execution_mode = execution_mode or self.settings.execution_mode
        self._paused = bool(self.settings.global_pause)
        self.approvals = ApprovalStore(time_provider=self.time_provider)
        engine_settings = self.settings.model_copy(update={"execution_mode": self.execution_mode})
        self.engine = PaperExecutionEngine(engine_settings, time_provider=self.time_provider)
        self.position_manager = PositionManager(time_provider=self.time_provider)
        self._trades: dict[str, Trade] = {}
        self._positions: dict[str, Position] = {}
        self.approvals_repo = approvals_repo
        self.trades_repo = trades_repo
        self.positions_repo = positions_repo
        self.events_repo = events_repo
        self.live_controller = live_controller
        self.portfolio_service = portfolio_service
        self.persistence_session_factory = (
            persistence_session_factory
            or (approvals_repo.session_factory if approvals_repo is not None else None)
            or (trades_repo.session_factory if trades_repo is not None else None)
            or (positions_repo.session_factory if positions_repo is not None else None)
            or (events_repo.session_factory if events_repo is not None else None)
        )

    async def stop(self) -> None:
        return None

    async def execute_live_assessment(self, assessment_id: str):
        if self.live_controller is None:
            raise RuntimeError("live_controller_unavailable")
        return await self.live_controller.execute_live_trade(assessment_id)

    async def evaluate_portfolio_candidates(
        self,
        assessment_ids: list[str],
        *,
        execution_mode: str | None = None,
    ):
        if self.portfolio_service is None:
            raise RuntimeError("portfolio_service_unavailable")
        return self.portfolio_service.evaluate_candidates(
            assessment_ids,
            execution_mode=execution_mode or self.execution_mode,
        )

    def recover_state(self) -> None:
        self.approvals = ApprovalStore(time_provider=self.time_provider)
        self._trades = {}
        self._positions = {}
        if self.approvals_repo is not None:
            for approval in self.approvals_repo.list_approvals(self.execution_mode):
                self.approvals.load_approval(approval)
        if self.trades_repo is not None:
            for trade in self.trades_repo.list_trades(self.execution_mode):
                self._trades[trade.trade_id] = trade
        if self.positions_repo is not None:
            for position in self.positions_repo.list_positions(self.execution_mode):
                self._positions[position.position_id] = position

    async def create_approval_from_assessment(self, assessment_id: str) -> Approval:
        assessment = self._get_assessment(assessment_id)
        if assessment is None:
            raise KeyError("assessment_not_found")
        existing = next(
            (approval for approval in self.approvals.list_all() if approval.assessment_id == assessment_id),
            None,
        )
        if existing is not None:
            return existing

        approval = self.approvals.create_from_assessment(assessment)
        approval = replace(approval, execution_mode=self.execution_mode)
        self.approvals.load_approval(approval)
        try:
            self._persist_approval(approval, event_type="approval_received")
        except Exception:
            self.approvals.remove(approval.approval_id)
            raise
        return approval

    async def approve_and_execute(self, approval_id: str) -> Approval:
        approval = self._get_or_restore_approval(approval_id)
        if approval is None:
            raise KeyError("approval_not_found")
        if approval.trade_id is not None and approval.position_id is not None:
            return approval

        if self.is_paused():
            raise ValueError("execution_paused")
        if await self._trading_blocked_by_market_data():
            raise ValueError("market_data_stale")

        assessment = self._get_assessment(approval.assessment_id)
        if assessment is None:
            raise KeyError("assessment_not_found")

        original_approval = replace(approval)
        approved = self.approvals.approve(approval_id)
        approved = replace(approved, execution_mode=self.execution_mode)
        self.approvals.load_approval(approved)

        latest_price = await self._get_latest_price(approved.symbol)
        execution = self.engine.execute(
            approved,
            assessment,
            latest_market_price=latest_price,
            paused=False,
        )
        trade = replace(execution.trade, execution_mode=self.execution_mode)
        position = replace(self.position_manager.open_position(execution.position), execution_mode=self.execution_mode)

        try:
            if self.persistence_session_factory is not None and self.approvals_repo and self.trades_repo and self.positions_repo:
                with self.persistence_session_factory.begin() as session:
                    self.approvals_repo.upsert_approval(approved, session=session)
                    self.trades_repo.upsert_trade(trade, session=session)
                    self.positions_repo.upsert_position(position, session=session)
                    executed = self.approvals.mark_executed(
                        approval_id,
                        trade_id=trade.trade_id,
                        position_id=position.position_id,
                    )
                    executed = replace(executed, execution_mode=self.execution_mode)
                    self.approvals.load_approval(executed)
                    self.approvals_repo.upsert_approval(executed, session=session)
                    self._append_event(
                        session=session,
                        event_type="trade_created",
                        entity_id=trade.trade_id,
                        trade_id=trade.trade_id,
                        symbol=trade.symbol,
                        payload={"approval_id": approved.approval_id, "execution_mode": self.execution_mode},
                    )
                    self._append_event(
                        session=session,
                        event_type="trade_executed",
                        entity_id=trade.trade_id,
                        trade_id=trade.trade_id,
                        symbol=trade.symbol,
                        payload={"position_id": position.position_id, "execution_mode": self.execution_mode},
                    )
            else:
                executed = self.approvals.mark_executed(
                    approval_id,
                    trade_id=trade.trade_id,
                    position_id=position.position_id,
                )
                executed = replace(executed, execution_mode=self.execution_mode)
                self.approvals.load_approval(executed)
        except Exception:
            self.approvals.load_approval(original_approval)
            raise

        self._trades[trade.trade_id] = trade
        self._positions[position.position_id] = position
        log_structured_event(
            logger,
            "trade_executed",
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            execution_mode=self.execution_mode,
        )
        return executed

    async def reject(self, approval_id: str, reason: str | None = None) -> Approval:
        approval = self._get_or_restore_approval(approval_id)
        if approval is None:
            raise KeyError("approval_not_found")
        rejected = self.approvals.reject(approval_id, reason=reason)
        rejected = replace(rejected, execution_mode=self.execution_mode)
        self.approvals.load_approval(rejected)
        self._persist_approval(rejected, event_type="approval_received")
        return rejected

    async def list_approvals(self) -> list[Approval]:
        await self.sync_positions_with_market()
        return self.approvals.list_all()

    async def list_pending_approvals(self) -> list[Approval]:
        await self.sync_positions_with_market()
        return self.approvals.list_pending()

    async def get_positions(self) -> list[Position]:
        await self.sync_positions_with_market()
        positions = list(self._positions.values())
        positions.sort(key=lambda item: item.opened_at, reverse=True)
        return [replace(position) for position in positions]

    async def get_position(self, position_id: str) -> Position | None:
        await self.sync_positions_with_market()
        position = self._positions.get(position_id)
        if position is None and self.positions_repo is not None:
            position = self.positions_repo.get_position(position_id)
            if position is not None:
                self._positions[position.position_id] = position
        return replace(position) if position is not None else None

    async def get_trades(self) -> list[Trade]:
        await self.sync_positions_with_market()
        trades = list(self._trades.values())
        trades.sort(key=lambda item: item.opened_at, reverse=True)
        return [replace(trade) for trade in trades]

    async def get_trade(self, trade_id: str) -> Trade | None:
        await self.sync_positions_with_market()
        trade = self._trades.get(trade_id)
        if trade is None and self.trades_repo is not None:
            trade = self.trades_repo.get_trade(trade_id)
            if trade is not None:
                self._trades[trade.trade_id] = trade
        return replace(trade) if trade is not None else None

    async def get_pnl_summary(self) -> PnlSummary:
        await self.sync_positions_with_market()
        return build_pnl_summary(list(self._positions.values()), list(self._trades.values()))

    async def close_open_positions(self, reason: str) -> None:
        for position_id, position in list(self._positions.items()):
            if position.status == "closed":
                continue
            trade = self._trades.get(position.trade_id)
            if trade is None:
                continue
            exit_price = await self._get_latest_price(position.symbol)
            if exit_price is None:
                exit_price = position.current_price or position.entry_price
            updated_position, updated_trade = self.position_manager.close_position(
                position,
                trade,
                exit_price,
                reason,
            )
            self._store_trade_position_updates(previous_position=position, position=updated_position, trade=updated_trade)
            self._positions[position_id] = updated_position
            self._trades[updated_trade.trade_id] = updated_trade

    async def sync_positions_with_market(self) -> None:
        for position_id, position in list(self._positions.items()):
            trade = self._trades.get(position.trade_id)
            if trade is None:
                continue

            latest_price = await self._get_latest_price(position.symbol)
            if latest_price is None:
                latest_price = position.current_price or position.entry_price

            updated_position, updated_trade = self.position_manager.update_market_price(
                position,
                trade,
                latest_price,
            )
            self._store_trade_position_updates(previous_position=position, position=updated_position, trade=updated_trade)
            self._positions[position_id] = updated_position
            self._trades[updated_trade.trade_id] = updated_trade

    async def pause(self) -> ControlStatus:
        self._set_pause_state(True)
        self._record_control_event("execution_paused")
        await self.sync_positions_with_market()
        return self.get_control_status()

    async def resume(self) -> ControlStatus:
        self._set_pause_state(False)
        self._record_control_event("execution_resumed")
        await self.sync_positions_with_market()
        return self.get_control_status()

    async def get_control_status_synced(self) -> ControlStatus:
        await self.sync_positions_with_market()
        return self.get_control_status()

    def get_control_status(self) -> ControlStatus:
        return ControlStatus(
            paused=self.is_paused(),
            execution_mode=self.execution_mode,
            paper_trading_enabled=self.settings.paper_trading_enabled,
            telegram_simulation_mode=self.settings.telegram_simulation_mode,
            timestamp=self.time_provider(),
        )

    def is_paused(self) -> bool:
        if self.settings.global_pause:
            return True
        if not self.use_persistent_control_state:
            return self._paused
        with SessionLocal() as session:
            state = session.get(SystemState, "global_pause")
            if state is None:
                return False
            try:
                payload = json.loads(state.value_json)
            except json.JSONDecodeError:
                return False
            return bool(payload.get("paused", False))

    def _set_pause_state(self, paused: bool) -> None:
        if not self.use_persistent_control_state:
            self._paused = paused
            return
        with SessionLocal() as session:
            state = session.get(SystemState, "global_pause")
            if state is None:
                state = SystemState(
                    key="global_pause",
                    value_json=json.dumps({"paused": paused}),
                    updated_at=self.time_provider(),
                )
                session.add(state)
            else:
                state.value_json = json.dumps({"paused": paused})
                state.updated_at = self.time_provider()
            session.commit()

    async def _get_latest_price(self, symbol: str) -> float | None:
        market_data_service = self.market_data_service
        if market_data_service is None:
            return None

        get_snapshot = getattr(market_data_service, "get_snapshot", None)
        if get_snapshot is None:
            return None

        snapshot = get_snapshot(symbol)
        if hasattr(snapshot, "__await__"):
            snapshot = await snapshot

        if snapshot is None:
            return None

        if isinstance(snapshot, dict):
            last_price = snapshot.get("last_price")
            return float(last_price) if last_price is not None else None

        ticker_snapshot = snapshot if isinstance(snapshot, TickerSnapshot) else snapshot
        last_price = getattr(ticker_snapshot, "last_price", None)
        return float(last_price) if last_price is not None else None

    async def _trading_blocked_by_market_data(self) -> bool:
        if not self.settings.stale_market_data_blocks_trading:
            return False
        market_data_service = self.market_data_service
        if market_data_service is None:
            return False
        get_health = getattr(market_data_service, "get_health", None)
        if get_health is None:
            return False
        try:
            health = get_health()
            if hasattr(health, "__await__"):
                health = await health
        except Exception:
            logger.exception("market data health check failed")
            return True
        if isinstance(health, dict):
            return health.get("status") != "ok"
        return getattr(health, "status", None) != "ok"

    def _get_assessment(self, assessment_id: str) -> RiskAssessment | None:
        risk_service = self.risk_service
        if risk_service is None:
            return None
        get_assessment = getattr(risk_service, "get_assessment", None)
        if get_assessment is None:
            return None
        return get_assessment(assessment_id)

    def _get_or_restore_approval(self, approval_id: str) -> Approval | None:
        approval = self.approvals.get(approval_id)
        if approval is None and self.approvals_repo is not None:
            approval = self.approvals_repo.get_approval(approval_id)
            if approval is not None:
                self.approvals.load_approval(approval)
        return approval

    def _persist_approval(self, approval: Approval, *, event_type: str) -> None:
        if self.persistence_session_factory is not None and self.approvals_repo is not None:
            with self.persistence_session_factory.begin() as session:
                self.approvals_repo.upsert_approval(approval, session=session)
                self._append_event(
                    session=session,
                    event_type=event_type,
                    entity_id=approval.approval_id,
                    trade_id=approval.trade_id,
                    symbol=approval.symbol,
                    payload={"status": approval.status, "reason": approval.rejection_reason},
                )
        log_structured_event(
            logger,
            event_type,
            approval_id=approval.approval_id,
            symbol=approval.symbol,
            status=approval.status,
            execution_mode=self.execution_mode,
        )

    def _store_trade_position_updates(self, *, previous_position: Position, position: Position, trade: Trade) -> None:
        if self.persistence_session_factory is not None and self.trades_repo is not None and self.positions_repo is not None:
            with self.persistence_session_factory.begin() as session:
                self.trades_repo.upsert_trade(trade, session=session)
                self.positions_repo.upsert_position(position, session=session)
                self._append_close_events(session=session, previous_position=previous_position, position=position, trade=trade)
        if previous_position.status != position.status and position.status == "closed":
            event_type = "trade_closed"
            if position.close_reason == "stop_loss":
                event_type = "stop_loss_hit"
            elif position.close_reason in {"target_1", "target_2"}:
                event_type = "take_profit_hit"
            log_structured_event(
                logger,
                event_type,
                trade_id=trade.trade_id,
                symbol=position.symbol,
                close_reason=position.close_reason,
                execution_mode=self.execution_mode,
            )

    def _append_close_events(self, *, session: Session, previous_position: Position, position: Position, trade: Trade) -> None:
        if previous_position.status == position.status or position.status != "closed":
            return
        event_type = "trade_closed"
        if position.close_reason == "stop_loss":
            event_type = "stop_loss_hit"
        elif position.close_reason in {"target_1", "target_2"}:
            event_type = "take_profit_hit"
        self._append_event(
            session=session,
            event_type=event_type,
            entity_id=position.position_id,
            trade_id=trade.trade_id,
            symbol=position.symbol,
            payload={"close_reason": position.close_reason, "realized_pnl": position.realized_pnl},
        )

    def _append_event(
        self,
        *,
        session: Session,
        event_type: str,
        entity_id: str | None,
        trade_id: str | None,
        symbol: str | None,
        payload: dict[str, object],
    ) -> None:
        if self.events_repo is None:
            return
        self.events_repo.append_event(
            event_type=event_type,
            entity_id=entity_id,
            trade_id=trade_id,
            symbol=symbol,
            execution_mode=self.execution_mode,
            payload=payload,
            session=session,
        )

    def _record_control_event(self, event_type: str) -> None:
        if self.events_repo is None:
            return
        self.events_repo.append_event(
            event_type=event_type,
            execution_mode=self.execution_mode,
            payload={
                "paused": event_type == "execution_paused",
                "execution_mode": self.execution_mode,
                "timestamp": self.time_provider().isoformat(),
            },
        )

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.logging import log_structured_event
from app.execution.service import ExecutionService
from app.persistence.repositories.events_repo import EventsRepository
from app.shadow.comparator import compare_position

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ShadowRunner:
    def __init__(
        self,
        *,
        signal_service: object,
        risk_service: object,
        execution_service: ExecutionService,
        market_data_service: object | None,
        auto_approve: bool,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.signal_service = signal_service
        self.risk_service = risk_service
        self.execution_service = execution_service
        self.market_data_service = market_data_service
        self.auto_approve = auto_approve
        self.events_repo = events_repo
        self._task: asyncio.Task[None] | None = None
        self.running = False
        self.last_cycle_at: datetime | None = None
        self.last_error: str | None = None
        self.blocked_reason: str | None = None

    async def start(self) -> None:
        self.running = True
        self.last_error = None
        self.blocked_reason = None

    async def stop(self) -> None:
        self.running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def run_cycle(self, symbols: list[str] | None = None) -> None:
        self.last_cycle_at = utc_now()
        if not self.running:
            self.blocked_reason = "shadow_not_running"
            return
        if self.execution_service.is_paused():
            self.blocked_reason = "global_pause"
            return

        if self.market_data_service is not None and hasattr(self.market_data_service, "get_health"):
            health = await self.market_data_service.get_health()
            status = health.get("status") if isinstance(health, dict) else getattr(health, "status", None)
            if self.execution_service.settings.stale_market_data_blocks_trading and status != "ok":
                self.blocked_reason = "stale_market_data"
                return

        try:
            signals = await self.signal_service.evaluate_symbols(symbols)
        except Exception as exc:
            self.last_error = str(exc)
            self.blocked_reason = "signal_failure"
            log_structured_event(logger, "shadow_signal_failure", reason=str(exc))
            return

        self.blocked_reason = None
        for signal in signals:
            try:
                assessment = await self.risk_service.validate_signal_payload(signal)
            except Exception as exc:
                self.last_error = str(exc)
                log_structured_event(logger, "shadow_risk_failure", symbol=signal.symbol, reason=str(exc))
                continue

            if assessment.final_decision != "approved_for_review":
                continue

            approval = await self.execution_service.create_approval_from_assessment(assessment.assessment_id)
            if not self.auto_approve:
                continue

            approval = await self.execution_service.approve_and_execute(approval.approval_id)
            position = await self.execution_service.get_position(approval.position_id) if approval.position_id else None
            if position is not None:
                comparison = compare_position(position)
                payload = {
                    "symbol": comparison.symbol,
                    "intended_entry": comparison.intended_entry,
                    "current_price": comparison.current_price,
                    "movement_pct": comparison.movement_pct,
                    "note": comparison.note,
                }
                if self.events_repo is not None:
                    self.events_repo.append_event(
                        event_type="shadow_trade_executed",
                        entity_id=position.position_id,
                        trade_id=position.trade_id,
                        symbol=position.symbol,
                        execution_mode="shadow",
                        payload=payload,
                    )
                log_structured_event(logger, "shadow_trade_executed", trade_id=position.trade_id, symbol=position.symbol, note=comparison.note)

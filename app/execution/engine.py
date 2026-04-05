from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from app.config.settings import Settings
from app.execution.types import Approval, ExecutionResult, Position, Trade
from app.risk.types import RiskAssessment


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PaperExecutionEngine:
    def __init__(self, settings: Settings, *, time_provider: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self.time_provider = time_provider or utc_now

    def execute(
        self,
        approval: Approval,
        assessment: RiskAssessment,
        *,
        latest_market_price: float | None,
        paused: bool,
    ) -> ExecutionResult:
        if approval.status != "approved":
            raise ValueError("approval_not_approved")
        if paused:
            raise ValueError("execution_paused")

        trade_plan = assessment.generated_trade_plan
        entry_price = self._resolve_price(
            latest_market_price,
            float(trade_plan.get("entry_price") or 0.0),
        )
        stop_loss = float(trade_plan.get("stop_loss") or 0.0)
        target_1 = float(trade_plan.get("target_1") or 0.0)
        raw_target_2 = trade_plan.get("target_2")
        target_2 = float(raw_target_2) if raw_target_2 is not None else None
        raw_position_size = trade_plan.get("position_size")
        quantity = float(raw_position_size) if raw_position_size is not None else 0.0

        if entry_price <= 0 or stop_loss <= 0 or target_1 <= 0 or quantity <= 0:
            raise ValueError("invalid_trade_plan")

        now = self.time_provider()
        trade_id = self._build_id("trd", approval.approval_id)
        position_id = self._build_id("pos", trade_id)

        trade = Trade(
            trade_id=trade_id,
            approval_id=approval.approval_id,
            assessment_id=approval.assessment_id,
            signal_id=approval.signal_id,
            position_id=position_id,
            symbol=approval.symbol,
            side=approval.side,
            strategy_name=approval.strategy_name,
            quantity=quantity,
            execution_price=entry_price,
            requested_entry_price=float(trade_plan.get("entry_price") or entry_price),
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            status="executed",
            execution_mode=self.settings.execution_mode,
            opened_at=now,
            updated_at=now,
        )

        position = Position(
            position_id=position_id,
            trade_id=trade_id,
            approval_id=approval.approval_id,
            assessment_id=approval.assessment_id,
            signal_id=approval.signal_id,
            symbol=approval.symbol,
            side=approval.side,
            strategy_name=approval.strategy_name,
            initial_quantity=quantity,
            quantity_open=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            status="open",
            opened_at=now,
            updated_at=now,
            execution_mode=self.settings.execution_mode,
        )

        return ExecutionResult(
            approval=replace(approval),
            trade=trade,
            position=position,
        )

    def _resolve_price(self, latest_market_price: float | None, fallback_entry_price: float) -> float:
        if latest_market_price is not None and latest_market_price > 0:
            return latest_market_price
        return fallback_entry_price

    def _build_id(self, prefix: str, value: str) -> str:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
        return f"{prefix}_{digest[:12]}"

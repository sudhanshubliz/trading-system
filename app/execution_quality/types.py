from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ExecutionQualityRecordData:
    record_id: str
    trade_id: str
    order_id: str | None
    symbol: str
    strategy_name: str
    mode: str
    intended_action: str
    execution_policy: str
    decision_timestamp: datetime | None
    submit_timestamp: datetime | None
    fill_timestamp: datetime | None
    intended_price: float | None
    arrival_mid_price: float | None
    actual_fill_price: float | None
    expected_slippage_bps: float | None
    realized_slippage_bps: float | None
    latency_ms: float | None
    partial_fill_ratio: float
    fill_quality_score: float
    notes: list[str]
    explanation: str
    recorded_at: datetime

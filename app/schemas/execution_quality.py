from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ExecutionQualityRecordResponse(BaseModel):
    record_id: str
    trade_id: str
    order_id: str | None = None
    symbol: str
    strategy_name: str
    mode: str
    intended_action: str
    execution_policy: str
    decision_timestamp: datetime | None = None
    submit_timestamp: datetime | None = None
    fill_timestamp: datetime | None = None
    intended_price: float | None = None
    arrival_mid_price: float | None = None
    actual_fill_price: float | None = None
    expected_slippage_bps: float | None = None
    realized_slippage_bps: float | None = None
    latency_ms: float | None = None
    partial_fill_ratio: float
    fill_quality_score: float
    notes: list[str] = Field(default_factory=list)
    explanation: str
    recorded_at: datetime


class ExecutionQualityRecordListResponse(BaseModel):
    items: list[ExecutionQualityRecordResponse] = Field(default_factory=list)
    count: int

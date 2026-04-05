from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SignalResponse(BaseModel):
    signal_id: str
    symbol: str
    side: str
    strategy_name: str
    confidence_score: int
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    reward_risk_ratio: float
    rationale: list[str]
    indicators_snapshot: dict[str, dict[str, float | None]]
    generated_at: datetime
    status: str


class SignalListResponse(BaseModel):
    items: list[SignalResponse]
    count: int


class SignalEvaluateRequest(BaseModel):
    symbols: list[str] | None = None


class SignalEvaluateResponse(BaseModel):
    items: list[SignalResponse]
    count: int

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.risk_locks import RiskLockEventResponse


class RiskCheckResponse(BaseModel):
    name: str
    passed: bool
    details: str | None = None


class RiskAssessmentResponse(BaseModel):
    assessment_id: str
    signal_id: str
    symbol: str
    side: str
    strategy_name: str
    final_decision: str
    account_balance: float
    max_risk_pct: float
    risk_amount: float
    stop_distance_abs: float
    stop_distance_pct: float
    position_size: float | None
    notional_value: float | None
    estimated_fee: float | None
    estimated_slippage_pct: float
    open_risk_pct_before: float
    open_risk_pct_after: float | None
    daily_drawdown_pct: float
    weekly_drawdown_pct: float
    min_reward_risk_ratio: float
    actual_reward_risk_ratio: float | None
    confidence_threshold: int
    risk_score: int
    trade_classification: str
    passed_checks_count: int
    failed_checks_count: int
    checks: list[RiskCheckResponse]
    rejection_reasons: list[str]
    generated_trade_plan: dict[str, float | str | bool | None]
    active_risk_locks: list[dict[str, object]] = Field(default_factory=list)
    assessed_at: datetime


class RiskSummaryResponse(BaseModel):
    account_balance: float
    equity: float
    available_balance: float
    open_risk_pct: float
    daily_drawdown_pct: float
    weekly_drawdown_pct: float
    max_risk_per_trade_pct: float
    max_concurrent_positions: int
    open_positions: int
    global_risk_lock: bool
    timestamp: datetime


class RiskValidateRequest(BaseModel):
    signal_id: str | None = None
    symbol: str
    side: str
    strategy_name: str
    confidence_score: int
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float | None = None
    reward_risk_ratio: float | None = None
    rationale: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


class RiskEvaluateSignalsRequest(BaseModel):
    symbols: list[str] | None = None


class RiskEvaluateSignalsResponse(BaseModel):
    items: list[RiskAssessmentResponse]
    count: int


class RiskLockEventListResponse(BaseModel):
    items: list[RiskLockEventResponse]
    count: int

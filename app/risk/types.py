from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class RiskValidationInput:
    signal_id: str
    symbol: str
    side: str
    strategy_name: str
    confidence_score: int
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float | None
    reward_risk_ratio: float | None
    rationale: list[str]
    generated_at: datetime
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class RiskCheckResult:
    name: str
    passed: bool
    details: str | None = None


@dataclass(slots=True)
class AccountState:
    balance: float
    equity: float
    available_balance: float
    realized_pnl_daily: float
    realized_pnl_weekly: float


@dataclass(slots=True)
class ExposureState:
    open_positions: int
    open_risk_pct: float
    reserved_risk_amount: float = 0.0


@dataclass(slots=True)
class RiskAssessment:
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
    checks: list[RiskCheckResult] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    generated_trade_plan: dict[str, float | str | bool | None] = field(default_factory=dict)
    active_risk_locks: list[dict[str, object]] = field(default_factory=list)
    assessed_at: datetime | None = None


@dataclass(slots=True)
class RiskSummary:
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

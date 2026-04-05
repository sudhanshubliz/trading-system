from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class OptimizationParameterGrid:
    ema_fast_periods: list[int] = field(default_factory=list)
    ema_slow_periods: list[int] = field(default_factory=list)
    rsi_periods: list[int] = field(default_factory=list)
    breakout_lookbacks: list[int] = field(default_factory=list)
    min_confidence_scores: list[int] = field(default_factory=list)
    min_reward_risk_ratios: list[float] = field(default_factory=list)


@dataclass(slots=True)
class OptimizationCandidateConfig:
    config_id: str
    ema_fast_period: int
    ema_slow_period: int
    rsi_period: int
    breakout_lookback: int
    min_confidence_score: int
    min_reward_risk_ratio: float


@dataclass(slots=True)
class WalkForwardFoldResult:
    fold_index: int
    train_start: datetime | None
    train_end: datetime | None
    test_start: datetime | None
    test_end: datetime | None
    metrics: dict[str, float | int]


@dataclass(slots=True)
class OptimizationResultRow:
    config_id: str
    parameters: dict[str, int | float]
    total_trades: int
    win_rate: float
    net_pnl: float
    expectancy: float
    profit_factor: float
    max_drawdown_pct: float
    average_hold_minutes: float
    robustness_score: float
    passed_guardrails: bool
    guardrail_failures: list[str]
    walk_forward_results: list[WalkForwardFoldResult] = field(default_factory=list)


@dataclass(slots=True)
class OptimizationRunResult:
    run_id: str
    status: str
    symbols: list[str]
    started_at: datetime
    completed_at: datetime | None
    total_combinations: int
    evaluated_combinations: int
    leaderboard: list[OptimizationResultRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

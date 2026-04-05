from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WalkForwardFoldResponse(BaseModel):
    fold_index: int
    train_start: datetime | None = None
    train_end: datetime | None = None
    test_start: datetime | None = None
    test_end: datetime | None = None
    metrics: dict[str, float | int]


class OptimizationResultRowResponse(BaseModel):
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
    walk_forward_results: list[WalkForwardFoldResponse]


class OptimizationRunRequest(BaseModel):
    symbols: list[str] | None = None
    initial_balance: float = 10000.0
    data_files: dict[str, dict[str, str]] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    max_bars: int | None = None
    parameter_grid: dict[str, list[int | float]] = Field(default_factory=dict)
    walk_forward_splits: int | None = None


class OptimizationRunResponse(BaseModel):
    run_id: str
    status: str
    symbols: list[str]
    started_at: datetime
    completed_at: datetime | None = None
    total_combinations: int
    evaluated_combinations: int
    notes: list[str]


class OptimizationRunListResponse(BaseModel):
    items: list[OptimizationRunResponse]
    count: int


class OptimizationLeaderboardResponse(BaseModel):
    items: list[OptimizationResultRowResponse]
    count: int

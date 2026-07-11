from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.market_data.types import Candle


@dataclass(slots=True)
class ReplayRunConfig:
    symbols: list[str]
    initial_balance: float
    candles: dict[str, dict[str, list[Candle]]]
    futures_candles: dict[str, dict[str, list[Candle]]] = field(default_factory=dict)
    strategy_overrides: dict[str, int | float] = field(default_factory=dict)
    risk_overrides: dict[str, int | float] = field(default_factory=dict)
    start_time: datetime | None = None
    end_time: datetime | None = None
    max_bars: int | None = None
    fidelity_mode: str = "medium"
    allow_partial_external_data: bool = True
    polymarket_snapshots: list[dict[str, object]] = field(default_factory=list)
    event_observations: list[dict[str, object]] = field(default_factory=list)
    wallet_observations: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class ReplayFidelityMetadata:
    run_id: str
    fidelity_mode: str
    external_dataset_summary: dict[str, int] = field(default_factory=dict)
    precision_claim: str = "best_effort"
    notes: list[str] = field(default_factory=list)
    generated_at: datetime | None = None


@dataclass(slots=True)
class EquityPoint:
    timestamp: datetime
    equity: float
    realized_pnl: float
    unrealized_pnl: float


@dataclass(slots=True)
class ReplayTradeResult:
    trade_id: str
    position_id: str
    symbol: str
    side: str
    strategy_name: str
    entry_price: float
    exit_price: float
    quantity: float
    opened_at: datetime
    closed_at: datetime | None
    realized_pnl: float
    exit_reason: str | None
    status: str
    gross_realized_pnl: float = 0.0
    fees_paid: float = 0.0
    slippage_cost: float = 0.0


@dataclass(slots=True)
class ReplayMetrics:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    max_drawdown_abs: float
    max_drawdown_pct: float
    realized_pnl_total: float
    unrealized_pnl_final: float
    ending_balance: float
    equity_curve: list[EquityPoint] = field(default_factory=list)
    gross_realized_pnl_total: float = 0.0
    fees_paid_total: float = 0.0
    slippage_cost_total: float = 0.0
    turnover_notional: float = 0.0


@dataclass(slots=True)
class ReplayRun:
    run_id: str
    status: str
    symbols: list[str]
    initial_balance: float
    total_steps: int
    started_at: datetime
    completed_at: datetime
    trades: list[ReplayTradeResult] = field(default_factory=list)
    metrics: ReplayMetrics | None = None
    phase2_artifacts: dict[str, object] = field(default_factory=dict)
    fidelity_notes: list[str] = field(default_factory=list)
    fidelity_mode: str = "medium"
    fidelity_metadata: ReplayFidelityMetadata | None = None


@dataclass(slots=True)
class WalkForwardFoldMetrics:
    fold_index: int
    start_time: datetime
    end_time: datetime
    total_trades: int
    net_pnl: float
    expectancy: float
    profit_factor: float
    max_drawdown_pct: float
    fees_paid: float
    slippage_cost: float
    turnover_notional: float
    passed: bool
    blockers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WalkForwardReplayReport:
    run_id: str
    start_time: datetime
    end_time: datetime
    evidence_days: float
    fold_count: int
    positive_fold_count: int
    required_positive_folds: int
    total_trades: int
    net_pnl: float
    expectancy: float
    profit_factor: float
    max_drawdown_pct: float
    fees_paid: float
    slippage_cost: float
    turnover_notional: float
    passed: bool
    blockers: list[str] = field(default_factory=list)
    folds: list[WalkForwardFoldMetrics] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    generated_at: datetime | None = None

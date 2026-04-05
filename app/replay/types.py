from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.market_data.types import Candle


@dataclass(slots=True)
class ReplayRunConfig:
    symbols: list[str]
    initial_balance: float
    candles: dict[str, dict[str, list[Candle]]]
    strategy_overrides: dict[str, int | float] = field(default_factory=dict)
    risk_overrides: dict[str, int | float] = field(default_factory=dict)
    start_time: datetime | None = None
    end_time: datetime | None = None
    max_bars: int | None = None


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

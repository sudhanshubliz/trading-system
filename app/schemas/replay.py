from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReplayCandleInput(BaseModel):
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True


class ReplayRunRequest(BaseModel):
    symbols: list[str] | None = None
    initial_balance: float = 10000.0
    candles: dict[str, dict[str, list[ReplayCandleInput]]] = Field(default_factory=dict)


class EquityPointResponse(BaseModel):
    timestamp: datetime
    equity: float
    realized_pnl: float
    unrealized_pnl: float


class ReplayTradeResultResponse(BaseModel):
    trade_id: str
    position_id: str
    symbol: str
    side: str
    strategy_name: str
    entry_price: float
    exit_price: float
    quantity: float
    opened_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float
    exit_reason: str | None = None
    status: str


class ReplayMetricsResponse(BaseModel):
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
    equity_curve: list[EquityPointResponse]


class ReplayRunResponse(BaseModel):
    run_id: str
    status: str
    symbols: list[str]
    initial_balance: float
    total_steps: int
    started_at: datetime
    completed_at: datetime
    trades: list[ReplayTradeResultResponse]
    metrics: ReplayMetricsResponse | None = None


class ReplayRunListResponse(BaseModel):
    items: list[ReplayRunResponse]
    count: int

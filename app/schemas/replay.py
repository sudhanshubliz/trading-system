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
    futures_candles: dict[str, dict[str, list[ReplayCandleInput]]] = Field(default_factory=dict)
    fidelity_mode: str = "medium"
    allow_partial_external_data: bool = True
    polymarket_snapshots: list[dict[str, object]] = Field(default_factory=list)
    event_observations: list[dict[str, object]] = Field(default_factory=list)
    wallet_observations: list[dict[str, object]] = Field(default_factory=list)


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
    gross_realized_pnl: float = 0.0
    fees_paid: float = 0.0
    slippage_cost: float = 0.0


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
    gross_realized_pnl_total: float = 0.0
    fees_paid_total: float = 0.0
    slippage_cost_total: float = 0.0
    turnover_notional: float = 0.0


class ReplayFidelityMetadataResponse(BaseModel):
    run_id: str
    fidelity_mode: str
    external_dataset_summary: dict[str, int] = Field(default_factory=dict)
    precision_claim: str
    notes: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


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
    phase2_artifacts: dict[str, object] = Field(default_factory=dict)
    fidelity_notes: list[str] = Field(default_factory=list)
    fidelity_mode: str = "medium"
    fidelity_metadata: ReplayFidelityMetadataResponse | None = None


class ReplayRunListResponse(BaseModel):
    items: list[ReplayRunResponse]
    count: int

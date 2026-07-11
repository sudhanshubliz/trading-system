from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ApprovalResponse(BaseModel):
    approval_id: str
    assessment_id: str
    signal_id: str
    symbol: str
    side: str
    strategy_name: str
    status: str
    created_at: datetime
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    executed_at: datetime | None = None
    rejection_reason: str | None = None
    trade_id: str | None = None
    position_id: str | None = None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalResponse]
    count: int


class RejectApprovalRequest(BaseModel):
    reason: str | None = None


class PositionResponse(BaseModel):
    position_id: str
    trade_id: str
    approval_id: str
    assessment_id: str
    signal_id: str
    symbol: str
    side: str
    strategy_name: str
    initial_quantity: float
    quantity_open: float
    entry_price: float
    current_price: float
    stop_loss: float
    target_1: float
    target_2: float | None = None
    status: str
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float
    gross_realized_pnl: float = 0.0
    fees_paid: float = 0.0
    slippage_cost: float = 0.0
    unrealized_pnl: float
    target_1_hit: bool
    close_reason: str | None = None
    fee_model: str = "fixed_bps"
    fee_rate: float = 0.0


class PositionListResponse(BaseModel):
    items: list[PositionResponse]
    count: int


class TradeResponse(BaseModel):
    trade_id: str
    approval_id: str
    assessment_id: str
    signal_id: str
    position_id: str
    symbol: str
    side: str
    strategy_name: str
    quantity: float
    execution_price: float
    requested_entry_price: float
    stop_loss: float
    target_1: float
    target_2: float | None = None
    status: str
    execution_mode: str
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float
    gross_realized_pnl: float = 0.0
    fees_paid: float = 0.0
    slippage_cost: float = 0.0
    fee_model: str = "fixed_bps"
    fee_rate: float = 0.0


class TradeListResponse(BaseModel):
    items: list[TradeResponse]
    count: int


class PnlResponse(BaseModel):
    realized_pnl_total: float
    unrealized_pnl_total: float
    daily_pnl: float
    open_positions: int
    closed_positions: int
    total_trades: int
    timestamp: datetime
    gross_realized_pnl_total: float = 0.0
    fees_paid_total: float = 0.0
    slippage_cost_total: float = 0.0


class ControlStatusResponse(BaseModel):
    paused: bool
    execution_mode: str
    paper_trading_enabled: bool
    telegram_simulation_mode: bool
    timestamp: datetime

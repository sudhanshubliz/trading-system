from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Approval:
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
    execution_mode: str = "paper"


@dataclass(slots=True)
class Trade:
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
    target_2: float | None
    status: str
    execution_mode: str
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float = 0.0
    client_order_id: str | None = None
    exchange_order_id: str | None = None
    exchange_status: str | None = None
    reconciliation_status: str | None = None
    last_reconciled_at: datetime | None = None
    failure_reason: str | None = None


@dataclass(slots=True)
class Position:
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
    target_2: float | None
    status: str
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    target_1_hit: bool = False
    close_reason: str | None = None
    execution_mode: str = "paper"
    reconciliation_status: str | None = None
    last_reconciled_at: datetime | None = None


@dataclass(slots=True)
class ExecutionResult:
    approval: Approval
    trade: Trade
    position: Position


@dataclass(slots=True)
class PnlSummary:
    realized_pnl_total: float
    unrealized_pnl_total: float
    daily_pnl: float
    open_positions: int
    closed_positions: int
    total_trades: int
    timestamp: datetime


@dataclass(slots=True)
class ControlStatus:
    paused: bool
    execution_mode: str
    paper_trading_enabled: bool
    telegram_simulation_mode: bool
    timestamp: datetime


@dataclass(slots=True)
class SyncResult:
    updated_positions: list[Position] = field(default_factory=list)

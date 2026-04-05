from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


class LiveLockType:
    GLOBAL_PAUSE = "GLOBAL_PAUSE"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "WEEKLY_LOSS_LIMIT"
    CONSECUTIVE_LOSS_LIMIT = "CONSECUTIVE_LOSS_LIMIT"
    OPEN_RISK_LIMIT = "OPEN_RISK_LIMIT"
    OPEN_POSITION_LIMIT = "OPEN_POSITION_LIMIT"
    EXCHANGE_SYNC_ERROR = "EXCHANGE_SYNC_ERROR"
    MANUAL_LIVE_DISARM = "MANUAL_LIVE_DISARM"
    LIVE_NOT_ARMED = "LIVE_NOT_ARMED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ORDER_VALIDATION_FAILED = "ORDER_VALIDATION_FAILED"
    ROLLOUT_POLICY_BLOCKED = "ROLLOUT_POLICY_BLOCKED"
    PORTFOLIO_POLICY_BLOCKED = "PORTFOLIO_POLICY_BLOCKED"


@dataclass(slots=True)
class LiveRiskLock:
    lock_id: str
    lock_type: str
    is_active: bool
    reason: str
    activated_at: datetime
    cleared_at: datetime | None = None
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(slots=True)
class LiveOrderRequest:
    assessment_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    limit_price: float | None
    stop_loss: float | None
    notional: float
    client_order_id: str


@dataclass(slots=True)
class LiveOrderResult:
    client_order_id: str
    exchange_order_id: str | None
    status: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    limit_price: float | None
    executed_price: float | None
    message: str | None = None
    raw_status: str | None = None


@dataclass(slots=True)
class LiveExecutionDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    active_locks: list[LiveRiskLock] = field(default_factory=list)
    order_request: LiveOrderRequest | None = None


@dataclass(slots=True)
class LiveExecutionResult:
    allowed: bool
    reasons: list[str]
    trade_id: str | None
    position_id: str | None
    client_order_id: str | None
    exchange_order_id: str | None
    status: str
    active_locks: list[LiveRiskLock] = field(default_factory=list)


@dataclass(slots=True)
class LiveStatus:
    enabled: bool
    armed: bool
    execution_mode: str
    can_execute: bool
    global_pause: bool
    active_locks: list[LiveRiskLock]
    stale_market_data: bool
    open_live_positions: int
    daily_live_pnl: float
    weekly_live_pnl: float
    timestamp: datetime


@dataclass(slots=True)
class LiveReconciliationResult:
    ok: bool
    mismatches: list[str] = field(default_factory=list)
    activated_lock_id: str | None = None
    timestamp: datetime | None = None


@dataclass(slots=True)
class StrategyCapitalRule:
    strategy_name: str
    max_capital_pct: float
    max_capital_amount: float


@dataclass(slots=True)
class SymbolCapitalRule:
    symbol: str
    max_capital_pct: float
    max_capital_amount: float


@dataclass(slots=True)
class RolloutPhaseRule:
    phase: str
    capital_limit: float
    strict_approval_required: bool
    max_open_positions: int


@dataclass(slots=True)
class CapitalAllocationState:
    deployed_capital: float
    remaining_capital: float
    open_position_count: int
    strategy_allocations: dict[str, float] = field(default_factory=dict)
    symbol_allocations: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class LiveRolloutState:
    current_phase: str
    current_capital_limit: float
    allowed_capital_limit: float
    strategy_allocations: dict[str, float] = field(default_factory=dict)
    symbol_allocations: dict[str, float] = field(default_factory=dict)
    last_phase_change_at: datetime | None = None
    changed_by: str | None = None
    reason: str | None = None
    rollback_active: bool = False
    notes: list[str] = field(default_factory=list)
    updated_at: datetime | None = None


@dataclass(slots=True)
class RolloutDecision:
    allowed: bool
    current_phase: str
    current_capital_limit: float
    allowed_capital_limit: float
    deployed_capital: float
    remaining_capital: float
    strategy_allocations: dict[str, float] = field(default_factory=dict)
    symbol_allocations: dict[str, float] = field(default_factory=dict)
    rollback_active: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RolloutHistoryEntry:
    event_type: str
    phase: str
    capital_limit: float
    changed_by: str | None = None
    reason: str | None = None
    rollback_active: bool = False
    timestamp: datetime | None = None

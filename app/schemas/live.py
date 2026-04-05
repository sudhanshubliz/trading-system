from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LiveLockResponse(BaseModel):
    lock_id: str
    lock_type: str
    is_active: bool
    reason: str
    activated_at: datetime
    cleared_at: datetime | None = None
    metadata: dict[str, str | int | float | bool | None]


class LiveLockListResponse(BaseModel):
    items: list[LiveLockResponse]
    count: int


class LiveStatusResponse(BaseModel):
    enabled: bool
    armed: bool
    execution_mode: str
    can_execute: bool
    global_pause: bool
    active_locks: list[LiveLockResponse]
    stale_market_data: bool
    open_live_positions: int
    daily_live_pnl: float
    weekly_live_pnl: float
    timestamp: datetime


class LiveExecutionResponse(BaseModel):
    allowed: bool
    reasons: list[str]
    trade_id: str | None = None
    position_id: str | None = None
    client_order_id: str | None = None
    exchange_order_id: str | None = None
    status: str
    active_locks: list[LiveLockResponse]


class LiveReconciliationResponse(BaseModel):
    ok: bool
    mismatches: list[str]
    activated_lock_id: str | None = None
    timestamp: datetime | None = None

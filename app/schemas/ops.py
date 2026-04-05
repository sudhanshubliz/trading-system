from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.live import LiveLockResponse


class AlertPayloadResponse(BaseModel):
    severity: str
    category: str
    message: str
    source: str
    created_at: datetime
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class OperatorStatusResponse(BaseModel):
    ops_enabled: bool
    deployment_mode: str
    global_pause: bool
    live_enabled: bool
    live_armed: bool
    live_can_execute: bool
    active_locks: list[LiveLockResponse]
    market_data_status: str
    market_data_fresh: bool
    exchange_connectivity: str
    reconciliation_status: str
    open_live_positions: int
    pending_approvals: int
    daily_live_pnl: float
    weekly_live_pnl: float
    startup_status: str
    recovery_status: str
    warnings: list[str]
    timestamp: datetime


class IncidentSummaryResponse(BaseModel):
    status: str
    active_lock_count: int
    critical_event_count: int
    pending_actions: list[str]
    items: list[AlertPayloadResponse]
    timestamp: datetime


class RecoveryReportResponse(BaseModel):
    recovery_type: str
    ok: bool
    open_positions_rebuilt: int
    pending_approvals_reloaded: int
    active_locks_reloaded: int
    live_armed: bool
    reconciliation_attempted: bool
    reconciliation_ok: bool | None = None
    issues: list[str]
    events_written: int
    timestamp: datetime

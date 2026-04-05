from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.live.types import LiveRiskLock


@dataclass(slots=True)
class StartupCheckResult:
    name: str
    status: str
    message: str
    critical: bool
    details: dict[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(slots=True)
class StartupCheckReport:
    status: str
    boot_ready: bool
    ready: bool
    results: list[StartupCheckResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    timestamp: datetime | None = None


@dataclass(slots=True)
class OperatorStatus:
    ops_enabled: bool
    deployment_mode: str
    global_pause: bool
    live_enabled: bool
    live_armed: bool
    live_can_execute: bool
    active_locks: list[LiveRiskLock] = field(default_factory=list)
    market_data_status: str = "unknown"
    market_data_fresh: bool = False
    exchange_connectivity: str = "unknown"
    reconciliation_status: str = "unknown"
    open_live_positions: int = 0
    pending_approvals: int = 0
    daily_live_pnl: float = 0.0
    weekly_live_pnl: float = 0.0
    startup_status: str = "unknown"
    recovery_status: str = "unknown"
    warnings: list[str] = field(default_factory=list)
    timestamp: datetime | None = None


@dataclass(slots=True)
class AlertPayload:
    severity: str
    category: str
    message: str
    source: str
    created_at: datetime
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(slots=True)
class IncidentSummary:
    status: str
    active_lock_count: int
    critical_event_count: int
    pending_actions: list[str] = field(default_factory=list)
    items: list[AlertPayload] = field(default_factory=list)
    timestamp: datetime | None = None


@dataclass(slots=True)
class RecoveryReport:
    recovery_type: str
    ok: bool
    open_positions_rebuilt: int
    pending_approvals_reloaded: int
    active_locks_reloaded: int
    live_armed: bool
    reconciliation_attempted: bool
    reconciliation_ok: bool | None
    issues: list[str] = field(default_factory=list)
    events_written: int = 0
    timestamp: datetime | None = None

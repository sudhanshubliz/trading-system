from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any

from app.config.settings import Settings, get_settings
from app.live.types import LiveLockType
from app.ops.alerts import build_incident_summary
from app.ops.recovery import RecoveryService
from app.ops.types import IncidentSummary, OperatorStatus, StartupCheckReport
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.locks_repo import LocksRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.ops.startup_checks import StartupCheckService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def build_operator_status(
    *,
    settings: Settings,
    startup_report: StartupCheckReport | None,
    recovery_report,
    execution_service: object | None,
    live_controller: object | None,
    market_data_service: object | None,
    approvals_repo: ApprovalsRepository | None,
) -> OperatorStatus:
    warnings: list[str] = []
    market_data_status = "unknown"
    market_data_fresh = False
    exchange_connectivity = "disabled" if not settings.enable_live_trading else "unknown"
    reconciliation_status = "disabled" if not settings.live_reconciliation_enabled else "unknown"
    active_locks = []
    live_enabled = bool(settings.enable_live_trading)
    live_armed = False
    live_can_execute = False
    open_live_positions = 0
    daily_live_pnl = 0.0
    weekly_live_pnl = 0.0

    if market_data_service is not None and hasattr(market_data_service, "get_health"):
        try:
            market_health = market_data_service.get_health()
            if inspect.isawaitable(market_health):
                market_health = await market_health
            market_data_status = (
                market_health.get("status", "unknown")
                if isinstance(market_health, dict)
                else getattr(market_health, "status", "unknown")
            )
            market_data_fresh = market_data_status == "ok"
        except Exception as exc:
            warnings.append(f"market_data_health_error:{exc}")
            market_data_status = "error"

    if live_controller is not None and hasattr(live_controller, "get_live_status"):
        try:
            live_status = await live_controller.get_live_status()
            active_locks = list(getattr(live_status, "active_locks", []))
            live_armed = bool(getattr(live_status, "armed", False))
            live_can_execute = bool(getattr(live_status, "can_execute", False))
            open_live_positions = int(getattr(live_status, "open_live_positions", 0))
            daily_live_pnl = float(getattr(live_status, "daily_live_pnl", 0.0))
            weekly_live_pnl = float(getattr(live_status, "weekly_live_pnl", 0.0))
            if any(lock.lock_type == LiveLockType.EXCHANGE_SYNC_ERROR for lock in active_locks):
                exchange_connectivity = "error"
                reconciliation_status = "failed"
            elif settings.enable_live_trading:
                exchange_connectivity = "configured"
                reconciliation_status = "ok" if settings.live_reconciliation_enabled else "disabled"
        except Exception as exc:
            warnings.append(f"live_status_error:{exc}")
            if settings.enable_live_trading:
                exchange_connectivity = "error"

    global_pause = False
    if execution_service is not None and hasattr(execution_service, "is_paused"):
        try:
            global_pause = bool(execution_service.is_paused())
        except Exception as exc:
            warnings.append(f"global_pause_check_error:{exc}")

    pending_approvals = 0
    if execution_service is not None and hasattr(execution_service, "list_pending_approvals"):
        try:
            items = await execution_service.list_pending_approvals()
            pending_approvals = len(items)
        except Exception as exc:
            warnings.append(f"pending_approvals_error:{exc}")
    elif approvals_repo is not None:
        pending_approvals = len(approvals_repo.list_pending("paper"))

    startup_status = startup_report.status if startup_report is not None else "unknown"
    recovery_status = "unknown"
    if recovery_report is not None:
        recovery_status = "ok" if recovery_report.ok else "degraded"
        if recovery_report.issues:
            warnings.extend(recovery_report.issues)

    if startup_report is not None:
        warnings.extend(startup_report.warnings)

    return OperatorStatus(
        ops_enabled=settings.ops_enabled,
        deployment_mode=settings.deployment_mode,
        global_pause=global_pause,
        live_enabled=live_enabled,
        live_armed=live_armed,
        live_can_execute=live_can_execute,
        active_locks=active_locks,
        market_data_status=str(market_data_status),
        market_data_fresh=market_data_fresh,
        exchange_connectivity=exchange_connectivity,
        reconciliation_status=reconciliation_status,
        open_live_positions=open_live_positions,
        pending_approvals=pending_approvals,
        daily_live_pnl=round(daily_live_pnl, 8),
        weekly_live_pnl=round(weekly_live_pnl, 8),
        startup_status=startup_status,
        recovery_status=recovery_status,
        warnings=sorted(set(warnings)),
        timestamp=utc_now(),
    )


class OpsService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        startup_checks: StartupCheckService | None = None,
        recovery_service: RecoveryService | None = None,
        execution_service: object | None = None,
        live_controller: object | None = None,
        market_data_service: object | None = None,
        approvals_repo: ApprovalsRepository | None = None,
        events_repo: EventsRepository | None = None,
        locks_repo: LocksRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.startup_checks = startup_checks
        self.recovery_service = recovery_service
        self.execution_service = execution_service
        self.live_controller = live_controller
        self.market_data_service = market_data_service
        self.approvals_repo = approvals_repo
        self.events_repo = events_repo
        self.locks_repo = locks_repo
        self._startup_report: StartupCheckReport | None = None

    def set_startup_report(self, report: StartupCheckReport | None) -> None:
        self._startup_report = report

    @property
    def startup_report(self) -> StartupCheckReport | None:
        return self._startup_report

    async def refresh_startup_report(self) -> StartupCheckReport | None:
        if self.startup_checks is None:
            return self._startup_report
        self._startup_report = await self.startup_checks.run_checks(write_probe_event=False)
        return self._startup_report

    async def get_operator_status(self) -> OperatorStatus:
        startup_report = self._startup_report
        recovery_report = self.recovery_service.last_report if self.recovery_service is not None else None
        return await build_operator_status(
            settings=self.settings,
            startup_report=startup_report,
            recovery_report=recovery_report,
            execution_service=self.execution_service,
            live_controller=self.live_controller,
            market_data_service=self.market_data_service,
            approvals_repo=self.approvals_repo,
        )

    async def get_incident_summary(self) -> IncidentSummary:
        operator_status = await self.get_operator_status()
        active_locks = operator_status.active_locks
        critical_events = []
        if self.events_repo is not None:
            critical_events = self.events_repo.list_critical_events(limit=self.settings.status_event_limit)
        return build_incident_summary(
            operator_status=operator_status,
            active_locks=active_locks,
            critical_events=critical_events,
        )

    async def run_recovery(self):
        if self.recovery_service is None:
            raise RuntimeError("recovery_service_unavailable")
        report = await self.recovery_service.run_manual_recovery()
        return report

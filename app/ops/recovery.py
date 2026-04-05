from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone

from app.config.settings import Settings, get_settings
from app.core.logging import log_structured_event
from app.ops.types import RecoveryReport
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.positions_repo import PositionsRepository

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_recovery_summary(
    *,
    recovery_type: str,
    ok: bool,
    open_positions_rebuilt: int,
    pending_approvals_reloaded: int,
    active_locks_reloaded: int,
    live_armed: bool,
    reconciliation_attempted: bool,
    reconciliation_ok: bool | None,
    issues: list[str],
    events_written: int,
) -> RecoveryReport:
    return RecoveryReport(
        recovery_type=recovery_type,
        ok=ok,
        open_positions_rebuilt=open_positions_rebuilt,
        pending_approvals_reloaded=pending_approvals_reloaded,
        active_locks_reloaded=active_locks_reloaded,
        live_armed=live_armed,
        reconciliation_attempted=reconciliation_attempted,
        reconciliation_ok=reconciliation_ok,
        issues=issues,
        events_written=events_written,
        timestamp=utc_now(),
    )


class RecoveryService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        execution_service: object | None = None,
        live_controller: object | None = None,
        approvals_repo: ApprovalsRepository | None = None,
        positions_repo: PositionsRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.execution_service = execution_service
        self.live_controller = live_controller
        self.approvals_repo = approvals_repo
        self.positions_repo = positions_repo
        self.events_repo = events_repo
        self._last_report: RecoveryReport | None = None

    @property
    def last_report(self) -> RecoveryReport | None:
        return self._last_report

    async def run_startup_recovery(self) -> RecoveryReport:
        report = await self._run_recovery("startup")
        self._last_report = report
        return report

    async def run_manual_recovery(self) -> RecoveryReport:
        report = await self._run_recovery("manual")
        self._last_report = report
        return report

    async def _run_recovery(self, recovery_type: str) -> RecoveryReport:
        issues: list[str] = []
        events_written = 0
        self._append_event(f"{recovery_type}_recovery_started", payload={"recovery_type": recovery_type})
        events_written += 1

        open_positions_rebuilt = 0
        pending_approvals_reloaded = 0
        active_locks_reloaded = 0
        live_armed = False
        reconciliation_attempted = False
        reconciliation_ok: bool | None = None

        try:
            if self.execution_service is not None and hasattr(self.execution_service, "recover_state"):
                self.execution_service.recover_state()
                if self.positions_repo is not None:
                    execution_mode = getattr(self.execution_service, "execution_mode", None)
                    open_positions_rebuilt = len(self.positions_repo.list_open_positions(execution_mode))
                if self.approvals_repo is not None:
                    execution_mode = getattr(self.execution_service, "execution_mode", "paper")
                    pending_approvals_reloaded = len(self.approvals_repo.list_pending(execution_mode))

            if self.live_controller is not None:
                lock_manager = getattr(self.live_controller, "lock_manager", None)
                if lock_manager is not None and hasattr(lock_manager, "recover"):
                    lock_manager.recover()
                    if hasattr(lock_manager, "list_active_locks"):
                        active_locks_reloaded = len(lock_manager.list_active_locks())
                if hasattr(self.live_controller, "get_live_status"):
                    live_status = await self.live_controller.get_live_status()
                    live_armed = bool(getattr(live_status, "armed", False))
                if (
                    self.settings.live_reconciliation_enabled
                    and self.settings.enable_live_trading
                    and hasattr(self.live_controller, "reconcile")
                ):
                    reconciliation_attempted = True
                    try:
                        result = await self.live_controller.reconcile()
                        reconciliation_ok = bool(getattr(result, "ok", False))
                        if not reconciliation_ok:
                            issues.extend(list(getattr(result, "mismatches", []) or []))
                    except Exception as exc:
                        reconciliation_ok = False
                        issues.append(f"live_reconciliation_failed:{exc}")
        except Exception as exc:
            logger.exception("recovery flow failed")
            issues.append(str(exc))

        ok = len(issues) == 0
        report = build_recovery_summary(
            recovery_type=recovery_type,
            ok=ok,
            open_positions_rebuilt=open_positions_rebuilt,
            pending_approvals_reloaded=pending_approvals_reloaded,
            active_locks_reloaded=active_locks_reloaded,
            live_armed=live_armed,
            reconciliation_attempted=reconciliation_attempted,
            reconciliation_ok=reconciliation_ok,
            issues=issues,
            events_written=events_written + 1,
        )
        self._append_event(
            f"{recovery_type}_recovery_{'completed' if ok else 'failed'}",
            payload=asdict(report),
        )
        log_structured_event(
            logger,
            f"{recovery_type}_recovery",
            ok=ok,
            issues=issues,
            open_positions_rebuilt=open_positions_rebuilt,
            pending_approvals_reloaded=pending_approvals_reloaded,
        )
        self._last_report = report
        return report

    def _append_event(self, event_type: str, *, payload: dict[str, object]) -> None:
        if self.events_repo is None:
            return
        self.events_repo.append_event(
            event_type=event_type,
            execution_mode="ops",
            payload=payload,
        )

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings, get_settings
from app.execution.telegram import TelegramRuntimeController
from app.ops.types import StartupCheckReport, StartupCheckResult
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.locks_repo import LocksRepository

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StartupCheckService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        persistence_session_factory: sessionmaker[Session] | None = None,
        events_repo: EventsRepository | None = None,
        locks_repo: LocksRepository | None = None,
        live_controller: object | None = None,
        market_data_service: object | None = None,
        persistence_available: bool = False,
        persistence_error: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.persistence_session_factory = persistence_session_factory
        self.events_repo = events_repo
        self.locks_repo = locks_repo
        self.live_controller = live_controller
        self.market_data_service = market_data_service
        self.persistence_available = persistence_available
        self.persistence_error = persistence_error

    async def run_checks(self, *, write_probe_event: bool = False) -> StartupCheckReport:
        results: list[StartupCheckResult] = []
        results.append(
            StartupCheckResult(
                name="settings_parse",
                status="passed",
                message="settings loaded successfully",
                critical=False,
                details={"deployment_mode": self.settings.deployment_mode},
            )
        )
        results.extend(self._check_config_contradictions())
        results.extend(self._check_persistence())
        results.extend(self._check_live_configuration())
        results.extend(self._check_telegram_runtime())
        results.extend(await self._check_market_data_requirement())
        if write_probe_event:
            results.append(self._check_event_store_probe())
        elif self.events_repo is not None and self.persistence_available:
            results.append(
                StartupCheckResult(
                    name="event_store",
                    status="passed",
                    message="event store repository configured",
                    critical=False,
                )
            )
        elif self.settings.persistence_enabled:
            results.append(
                StartupCheckResult(
                    name="event_store",
                    status="failed" if self.settings.require_persistence_for_boot else "warning",
                    message="event store repository unavailable",
                    critical=self.settings.require_persistence_for_boot,
                )
            )

        failures = [item.message for item in results if item.status == "failed"]
        warnings = [item.message for item in results if item.status == "warning"]
        boot_ready = len([item for item in results if item.status == "failed" and item.critical]) == 0
        ready = len(failures) == 0
        status = "ok" if ready else ("degraded" if boot_ready else "failed")
        report = StartupCheckReport(
            status=status,
            boot_ready=boot_ready,
            ready=ready,
            results=results,
            warnings=warnings,
            failures=failures,
            timestamp=utc_now(),
        )
        return report

    def _check_config_contradictions(self) -> list[StartupCheckResult]:
        results: list[StartupCheckResult] = []
        if not self.settings.live_allow_limit_orders and not self.settings.live_allow_market_orders:
            results.append(
                StartupCheckResult(
                    name="config_contradictions",
                    status="failed",
                    message="live execution has no allowed order types",
                    critical=True,
                )
            )
        elif self.settings.live_execution_mode == "live" and not self.settings.enable_live_trading:
            results.append(
                StartupCheckResult(
                    name="config_contradictions",
                    status="warning",
                    message="live execution mode selected while live trading is disabled",
                    critical=False,
                )
            )
        else:
            results.append(
                StartupCheckResult(
                    name="config_contradictions",
                    status="passed",
                    message="no critical config contradictions detected",
                    critical=False,
                )
            )
        return results

    def _check_persistence(self) -> list[StartupCheckResult]:
        if not self.settings.persistence_enabled:
            return [
                StartupCheckResult(
                    name="persistence",
                    status="warning",
                    message="persistence disabled by configuration",
                    critical=False,
                )
            ]

        persistence_required = self.settings.require_persistence_for_boot or self.settings.readiness_requires_persistence
        severity = "failed" if persistence_required else "warning"
        critical = self.settings.require_persistence_for_boot

        if not self.persistence_available or self.persistence_session_factory is None:
            return [
                StartupCheckResult(
                    name="persistence",
                    status=severity,
                    message=self.persistence_error or "persistence database unavailable",
                    critical=critical,
                )
            ]

        try:
            with self.persistence_session_factory() as session:
                session.execute(text("SELECT 1")).scalar_one()
                inspector = sqlalchemy_inspect(session.bind)
                tables = set(inspector.get_table_names())
        except SQLAlchemyError as exc:
            logger.exception("startup persistence check failed")
            return [
                StartupCheckResult(
                    name="persistence",
                    status=severity,
                    message=f"persistence check failed: {exc}",
                    critical=critical,
                )
            ]

        required_tables = {"persisted_events", "persisted_trades", "persisted_positions"}
        missing_tables = sorted(required_tables - tables)
        results = [
            StartupCheckResult(
                name="persistence",
                status="passed",
                message="persistence database reachable",
                critical=False,
            )
        ]
        if missing_tables:
            results.append(
                StartupCheckResult(
                    name="persistence_tables",
                    status=severity,
                    message="required persistence tables are missing",
                    critical=critical,
                    details={"missing_tables": ",".join(missing_tables)},
                )
            )
        else:
            results.append(
                StartupCheckResult(
                    name="persistence_tables",
                    status="passed",
                    message="required persistence tables present",
                    critical=False,
                )
            )
        return results

    def _check_live_configuration(self) -> list[StartupCheckResult]:
        if not self.settings.enable_live_trading:
            return [
                StartupCheckResult(
                    name="live_configuration",
                    status="passed",
                    message="live trading disabled by default-safe configuration",
                    critical=False,
                )
            ]

        results: list[StartupCheckResult] = []
        missing_credentials = []
        if not self.settings.binance_api_key:
            missing_credentials.append("BINANCE_API_KEY")
        if not self.settings.binance_api_secret:
            missing_credentials.append("BINANCE_API_SECRET")

        if missing_credentials:
            results.append(
                StartupCheckResult(
                    name="live_credentials",
                    status="failed",
                    message="live trading enabled but Binance credentials are missing",
                    critical=True,
                    details={"missing": ",".join(missing_credentials)},
                )
            )
        else:
            results.append(
                StartupCheckResult(
                    name="live_credentials",
                    status="passed",
                    message="live trading credentials configured",
                    critical=False,
                )
            )

        if self.live_controller is None:
            results.append(
                StartupCheckResult(
                    name="live_controller",
                    status="failed",
                    message="live controller unavailable while live trading is enabled",
                    critical=True,
                )
            )
        else:
            results.append(
                StartupCheckResult(
                    name="live_controller",
                    status="passed",
                    message="live controller available",
                    critical=False,
                )
            )

        if self.locks_repo is None:
            results.append(
                StartupCheckResult(
                    name="live_lock_store",
                    status="failed",
                    message="live lock store unavailable while live trading is enabled",
                    critical=True,
                )
            )
        else:
            results.append(
                StartupCheckResult(
                    name="live_lock_store",
                    status="passed",
                    message="live lock store available",
                    critical=False,
                )
            )
        return results

    def _check_telegram_runtime(self) -> list[StartupCheckResult]:
        if not self.settings.telegram_runtime_enabled:
            return [
                StartupCheckResult(
                    name="telegram_runtime",
                    status="warning",
                    message="telegram runtime disabled",
                    critical=False,
                )
            ]

        try:
            TelegramRuntimeController()
        except Exception as exc:
            return [
                StartupCheckResult(
                    name="telegram_runtime",
                    status="warning",
                    message=f"telegram runtime initialization warning: {exc}",
                    critical=False,
                )
            ]
        return [
            StartupCheckResult(
                name="telegram_runtime",
                status="passed",
                message="telegram runtime controller can initialize locally",
                critical=False,
            )
        ]

    async def _check_market_data_requirement(self) -> list[StartupCheckResult]:
        if not self.settings.enable_live_trading or not self.settings.require_market_data_for_live:
            return [
                StartupCheckResult(
                    name="market_data_requirement",
                    status="passed",
                    message="market data readiness not required for boot",
                    critical=False,
                )
            ]

        service = self.market_data_service
        if service is None:
            return [
                StartupCheckResult(
                    name="market_data_requirement",
                    status="failed",
                    message="market data service unavailable while required for live readiness",
                    critical=True,
                )
            ]

        try:
            health_value = getattr(service, "get_health", None)
            if health_value is None:
                raise RuntimeError("market data health hook missing")
            health = health_value()
            if inspect.isawaitable(health):
                health = await health
        except Exception as exc:
            return [
                StartupCheckResult(
                    name="market_data_requirement",
                    status="failed",
                    message=f"market data readiness check failed: {exc}",
                    critical=True,
                )
            ]

        status_value = health.get("status") if isinstance(health, dict) else getattr(health, "status", "unknown")
        if status_value != "ok":
            return [
                StartupCheckResult(
                    name="market_data_requirement",
                    status="failed",
                    message="market data is not ready for live mode",
                    critical=True,
                    details={"market_data_status": str(status_value)},
                )
            ]

        return [
            StartupCheckResult(
                name="market_data_requirement",
                status="passed",
                message="market data readiness confirmed for live mode",
                critical=False,
            )
        ]

    def _check_event_store_probe(self) -> StartupCheckResult:
        severity = "failed" if self.settings.require_persistence_for_boot else "warning"
        critical = self.settings.require_persistence_for_boot
        if self.events_repo is None:
            return StartupCheckResult(
                name="event_store",
                status=severity,
                message="event store repository unavailable",
                critical=critical,
            )

        try:
            self.events_repo.append_event(
                event_type="startup_preflight_probe",
                execution_mode="ops",
                payload={"timestamp": utc_now().isoformat()},
            )
        except Exception as exc:
            logger.exception("startup event probe failed")
            return StartupCheckResult(
                name="event_store",
                status=severity,
                message=f"event store probe failed: {exc}",
                critical=critical,
            )

        return StartupCheckResult(
            name="event_store",
            status="passed",
            message="event store write probe succeeded",
            critical=False,
        )

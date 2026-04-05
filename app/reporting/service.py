from __future__ import annotations

from typing import Any

from app.config.settings import Settings, get_settings
from app.persistence.repositories.reports_repo import ReportsRepository
from app.reporting.aggregator import ReportAggregator


class ReportingService:
    def __init__(
        self,
        aggregator: ReportAggregator,
        *,
        settings: Settings | None = None,
        reports_repo: ReportsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.aggregator = aggregator
        self.reports_repo = reports_repo

    async def stop(self) -> None:
        return None

    def build_report(self, scope: str, execution_mode: str | None = None) -> dict[str, Any]:
        report = self.aggregator.build_scope_report(scope, execution_mode=execution_mode)
        if self.reports_repo is not None:
            scope_key = execution_mode or "latest"
            self.reports_repo.upsert_report(
                report_id=f"{scope}:{scope_key}",
                scope=scope,
                scope_key=scope_key,
                generated_at=report["generated_at"],
                payload=report,
            )
        return report

    def get_daily_report(self, execution_mode: str | None = None) -> dict[str, Any]:
        return self.build_report("daily", execution_mode=execution_mode)

    def get_weekly_report(self, execution_mode: str | None = None) -> dict[str, Any]:
        return self.build_report("weekly", execution_mode=execution_mode)

    def get_strategy_report(self, execution_mode: str | None = None) -> dict[str, Any]:
        return self.build_report("strategy", execution_mode=execution_mode)

    def get_symbol_report(self, execution_mode: str | None = None) -> dict[str, Any]:
        return self.build_report("symbol", execution_mode=execution_mode)

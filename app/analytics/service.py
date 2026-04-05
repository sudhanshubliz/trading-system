from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.analytics.attribution import (
    build_portfolio_metrics,
    build_strategy_attribution,
    build_symbol_attribution,
)
from app.analytics.regime import VALID_REGIMES, classify_regime
from app.analytics.types import RegimeSummary
from app.config.settings import Settings, get_settings
from app.persistence.db import utc_now
from app.persistence.repositories.analytics_repo import AnalyticsRepository
from app.persistence.repositories.trades_repo import TradesRepository


class AnalyticsService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        trades_repo: TradesRepository | None = None,
        analytics_repo: AnalyticsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.trades_repo = trades_repo
        self.analytics_repo = analytics_repo

    def get_portfolio_metrics(self, execution_mode: str | None = None) -> dict[str, Any]:
        metrics = build_portfolio_metrics(
            self._list_trades(execution_mode),
            settings=self.settings,
            execution_mode=execution_mode,
        )
        payload = asdict(metrics)
        self._persist("portfolio_metrics", payload, scope_key=execution_mode or "all", execution_mode=execution_mode)
        return payload

    def get_strategy_attribution(self, execution_mode: str | None = None) -> dict[str, Any]:
        items = build_strategy_attribution(
            self._list_trades(execution_mode),
            settings=self.settings,
            execution_mode=execution_mode,
        )
        payload = {"items": [asdict(item) for item in items], "count": len(items), "timestamp": utc_now()}
        self._persist("strategy_attribution", payload, scope_key=execution_mode or "all", execution_mode=execution_mode)
        return payload

    def get_symbol_attribution(self, execution_mode: str | None = None) -> dict[str, Any]:
        items = build_symbol_attribution(self._list_trades(execution_mode), execution_mode=execution_mode)
        payload = {"items": [asdict(item) for item in items], "count": len(items), "timestamp": utc_now()}
        self._persist("symbol_attribution", payload, scope_key=execution_mode or "all", execution_mode=execution_mode)
        return payload

    def get_regime_summary(self, execution_mode: str | None = None) -> dict[str, Any]:
        trades = self._list_trades(execution_mode)
        current_regime = classify_regime(
            trades,
            volatility_lookback=self.settings.regime_volatility_lookback,
            trend_lookback=self.settings.regime_trend_lookback,
        )
        strategy_attribution = build_strategy_attribution(trades, settings=self.settings, execution_mode=execution_mode)
        strategy_regime_leaders = {
            item.strategy_name: max(item.regime_breakdown, key=item.regime_breakdown.get)
            for item in strategy_attribution
            if item.regime_breakdown
        }
        summary = RegimeSummary(
            current_regime=current_regime,
            supported_regimes=list(VALID_REGIMES),
            strategy_regime_leaders=strategy_regime_leaders,
            timestamp=utc_now(),
        )
        payload = asdict(summary)
        self._persist("regime_summary", payload, scope_key=execution_mode or "all", execution_mode=execution_mode)
        return payload

    def get_attribution_summary(self, execution_mode: str | None = None) -> dict[str, Any]:
        payload = {
            "portfolio": self.get_portfolio_metrics(execution_mode),
            "strategies": self.get_strategy_attribution(execution_mode),
            "symbols": self.get_symbol_attribution(execution_mode),
            "regime": self.get_regime_summary(execution_mode),
            "timestamp": utc_now(),
        }
        self._persist("attribution_summary", payload, scope_key=execution_mode or "all", execution_mode=execution_mode)
        return payload

    def _list_trades(self, execution_mode: str | None = None):
        if self.trades_repo is None:
            return []
        return self.trades_repo.list_trades(execution_mode)

    def _persist(
        self,
        report_type: str,
        payload: dict[str, Any],
        *,
        scope_key: str,
        execution_mode: str | None,
    ) -> None:
        if self.analytics_repo is None:
            return
        self.analytics_repo.upsert_report(
            report_type=report_type,
            scope_key=scope_key,
            execution_mode=execution_mode,
            payload=payload,
        )

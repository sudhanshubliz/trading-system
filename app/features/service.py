from __future__ import annotations

import hashlib
import inspect
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable

from app.config.settings import Settings, get_settings
from app.features.tradingview_like.engine import TradingViewLikeFeatureEngine
from app.features.tradingview_like.registry import FEATURE_CATALOG
from app.features.tradingview_like.types import FeatureCatalogEntry, FeatureRun
from app.market_data.types import TickerSnapshot
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.feature_runs_repo import FeatureRunsRepository
from app.signals.schemas import normalize_requested_symbols

from app.alpha_fusion.types import AlphaFeatureSnapshot

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FeatureService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        market_data_service: object | None = None,
        feature_engine: TradingViewLikeFeatureEngine | None = None,
        feature_runs_repo: FeatureRunsRepository | None = None,
        events_repo: EventsRepository | None = None,
        time_provider: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[str, datetime], str] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.market_data_service = market_data_service
        self.feature_engine = feature_engine or TradingViewLikeFeatureEngine(self.settings)
        self.feature_runs_repo = feature_runs_repo
        self.events_repo = events_repo
        self.time_provider = time_provider or utc_now
        self.run_id_factory = run_id_factory or self._default_run_id_factory
        self.supported_symbols = [symbol.upper() for symbol in self.settings.signals_supported_symbols]

    def get_catalog(self) -> list[FeatureCatalogEntry]:
        return list(FEATURE_CATALOG)

    async def compute_symbol(
        self,
        symbol: str,
        *,
        generated_at: datetime | None = None,
        persist: bool = True,
    ) -> FeatureRun | None:
        normalized_symbol = symbol.upper()
        if normalized_symbol not in self.supported_symbols or self.market_data_service is None:
            return None

        candles_by_timeframe = await self._load_symbol_candles(normalized_symbol)
        if candles_by_timeframe is None:
            return None

        market_snapshot = await self._load_market_snapshot(normalized_symbol)
        run_time = generated_at or self.time_provider()
        snapshot = self.feature_engine.build_snapshot(
            symbol=normalized_symbol,
            candles_by_timeframe=candles_by_timeframe,
            generated_at=run_time,
            market_price=market_snapshot.last_price if market_snapshot is not None else None,
        )
        if snapshot is None:
            return None

        run = FeatureRun(
            run_id=self.run_id_factory(normalized_symbol, run_time),
            symbol=normalized_symbol,
            source_name="tradingview_like",
            status="computed",
            generated_at=run_time,
            timeframes=sorted(snapshot.timeframes),
            catalog_version=self.settings.app_version,
            feature_snapshot=snapshot,
            metadata={
                "supported_timeframes": list(self.settings.alpha_feature_timeframes),
                "catalog_size": len(FEATURE_CATALOG),
            },
        )
        if persist:
            self._store_run(run)
        return run

    async def compute_batch(
        self,
        symbols: list[str] | None = None,
        *,
        generated_at: datetime | None = None,
    ) -> list[FeatureRun]:
        normalized_symbols = normalize_requested_symbols(symbols) or self.supported_symbols
        items: list[FeatureRun] = []
        for symbol in normalized_symbols:
            run = await self.compute_symbol(symbol, generated_at=generated_at, persist=True)
            if run is not None:
                items.append(run)
        return items

    def list_runs(
        self,
        *,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[FeatureRun]:
        if self.feature_runs_repo is None:
            return []
        return self.feature_runs_repo.list_runs(symbol=symbol, limit=limit or self.settings.feature_store_limit)

    def latest_snapshot(self, symbol: str) -> AlphaFeatureSnapshot | None:
        if self.feature_runs_repo is None:
            return None
        run = self.feature_runs_repo.get_latest_run(symbol.upper())
        if run is None:
            return None
        return run.feature_snapshot

    async def _load_symbol_candles(self, symbol: str) -> dict[str, list[object]] | None:
        candles_by_timeframe: dict[str, list[object]] = {}
        get_candles = getattr(self.market_data_service, "get_candles", None)
        if get_candles is None:
            return None

        required_count = max(
            self.settings.signals_min_candle_count,
            self.settings.ema_slow_period + 2,
            self.settings.alpha_atr_period + 2,
            self.settings.breakout_lookback + 2,
            self.settings.feature_bollinger_period + 2,
            self.settings.feature_market_structure_lookback + 2,
        )
        for timeframe in self.settings.alpha_feature_timeframes:
            candles = await self._maybe_await(get_candles(symbol, timeframe))
            if not candles or len(candles) < required_count:
                return None
            candles_by_timeframe[timeframe] = candles
        return candles_by_timeframe

    async def _load_market_snapshot(self, symbol: str) -> TickerSnapshot | None:
        get_snapshot = getattr(self.market_data_service, "get_snapshot", None)
        if get_snapshot is None:
            return None
        snapshot = await self._maybe_await(get_snapshot(symbol))
        if isinstance(snapshot, TickerSnapshot):
            return snapshot
        if isinstance(snapshot, dict):
            return TickerSnapshot(**snapshot)
        return None

    async def _maybe_await(self, value: object) -> object:
        if inspect.isawaitable(value):
            return await value
        return value

    def _store_run(self, run: FeatureRun) -> None:
        if self.feature_runs_repo is not None:
            self.feature_runs_repo.upsert_run(run)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="feature_run_computed",
                entity_id=run.run_id,
                symbol=run.symbol,
                payload={
                    "source_name": run.source_name,
                    "status": run.status,
                    "timeframes": run.timeframes,
                    "feature_coverage": run.feature_snapshot.feature_coverage,
                    "feature_snapshot": asdict(run.feature_snapshot),
                },
            )

    def _default_run_id_factory(self, symbol: str, generated_at: datetime) -> str:
        seed = "|".join([symbol.upper(), generated_at.astimezone(timezone.utc).isoformat()])
        return f"feature_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"

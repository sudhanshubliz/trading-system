from __future__ import annotations

import inspect
import logging
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.config.settings import Settings, get_settings
from app.core.logging import log_structured_event
from app.indicators.ema import calculate_ema
from app.indicators.macd import calculate_macd
from app.indicators.rsi import calculate_rsi
from app.indicators.vwap import calculate_vwap
from app.market_data.types import Candle
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.signals_repo import SignalsRepository
from app.signals.schemas import normalize_requested_symbols
from app.signals.types import CandidateSignal, IndicatorSnapshot, SignalEvaluationResult, TimeframeIndicatorSnapshot
from app.strategies.base import StrategyContext
from app.strategies.breakout import BreakoutConfirmationStrategy
from app.strategies.trend_follow import TrendFollowContinuationStrategy

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SignalService:
    def __init__(
        self,
        settings: Settings | None = None,
        market_data_service: object | None = None,
        *,
        time_provider: Callable[[], datetime] | None = None,
        signal_id_factory: Callable[[str, str, str, datetime], str] | None = None,
        signals_repo: SignalsRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.market_data_service = market_data_service
        self.time_provider = time_provider or utc_now
        self.signal_id_factory = signal_id_factory or self._default_signal_id_factory
        self.signals_repo = signals_repo
        self.events_repo = events_repo
        self.supported_symbols = [symbol.upper() for symbol in self.settings.signals_supported_symbols]
        self.strategies = [
            TrendFollowContinuationStrategy(),
            BreakoutConfirmationStrategy(),
        ]
        self._signals: list[CandidateSignal] = []

    async def stop(self) -> None:
        return None

    async def evaluate_symbols(
        self,
        symbols: list[str] | None = None,
        *,
        generated_at: datetime | None = None,
    ) -> list[CandidateSignal]:
        normalized_symbols = normalize_requested_symbols(symbols) or self.supported_symbols
        market_data_service = self.market_data_service
        if market_data_service is None:
            logger.warning("signal evaluation skipped because market data service is unavailable")
            return []

        if not await self._market_data_is_healthy_enough(market_data_service):
            return []

        generated_signals: list[CandidateSignal] = []
        evaluation_time = generated_at or self.time_provider()
        for symbol in normalized_symbols:
            if symbol not in self.supported_symbols:
                continue

            candles_by_timeframe = await self._load_symbol_candles(symbol)
            if candles_by_timeframe is None:
                continue

            indicators = self._build_indicator_snapshot(candles_by_timeframe)
            if indicators is None:
                continue

            context = StrategyContext(
                symbol=symbol,
                regime_candles=candles_by_timeframe[self.settings.signals_regime_timeframe],
                setup_candles=candles_by_timeframe[self.settings.signals_setup_timeframe],
                trigger_candles=candles_by_timeframe[self.settings.signals_trigger_timeframe],
                indicators=indicators,
                settings=self.settings,
                generated_at=evaluation_time,
                signal_id_factory=self.signal_id_factory,
            )

            for strategy in self.strategies:
                signal = strategy.evaluate(context)
                if signal is None:
                    continue
                if not self._can_emit_signal(signal):
                    continue
                self._store_signal(signal)
                generated_signals.append(signal)

        return generated_signals

    def get_signals(
        self,
        *,
        symbol: str | None = None,
        strategy_name: str | None = None,
        limit: int | None = None,
    ) -> list[CandidateSignal]:
        items = self._signals
        if symbol is not None:
            normalized_symbol = symbol.upper()
            items = [item for item in items if item.symbol == normalized_symbol]
        if strategy_name is not None:
            items = [item for item in items if item.strategy_name == strategy_name]
        if limit is not None:
            items = items[: max(limit, 0)]
        return [replace(item) for item in items]

    def get_signal(self, signal_id: str) -> CandidateSignal | None:
        for signal in self._signals:
            if signal.signal_id == signal_id:
                return replace(signal)
        if self.signals_repo is not None:
            signal = self.signals_repo.get_signal(signal_id)
            if signal is not None:
                self._store_signal(signal)
                return replace(signal)
        return None

    def get_evaluation_result(self, items: list[CandidateSignal]) -> SignalEvaluationResult:
        return SignalEvaluationResult(items=items, count=len(items))

    async def _market_data_is_healthy_enough(self, market_data_service: object) -> bool:
        get_health = getattr(market_data_service, "get_health", None)
        if get_health is None:
            return True

        try:
            health = await self._maybe_await(get_health())
        except Exception:
            logger.warning("signal evaluation skipped because market data health lookup failed")
            return False

        if isinstance(health, dict):
            return health.get("status") == "ok"

        status = getattr(health, "status", None)
        return status == "ok"

    async def _load_symbol_candles(self, symbol: str) -> dict[str, list[Candle]] | None:
        assert self.market_data_service is not None
        candles_by_timeframe: dict[str, list[Candle]] = {}

        for timeframe in (
            self.settings.signals_regime_timeframe,
            self.settings.signals_setup_timeframe,
            self.settings.signals_trigger_timeframe,
        ):
            get_candles = getattr(self.market_data_service, "get_candles", None)
            if get_candles is None:
                return None

            candles = await self._maybe_await(get_candles(symbol, timeframe))
            if not candles or len(candles) < self.settings.signals_min_candle_count:
                return None
            candles_by_timeframe[timeframe] = candles

        return candles_by_timeframe

    def _build_indicator_snapshot(
        self,
        candles_by_timeframe: dict[str, list[Candle]],
    ) -> IndicatorSnapshot | None:
        snapshot = IndicatorSnapshot()
        for timeframe, candles in candles_by_timeframe.items():
            closes = [candle.close for candle in candles]
            highs = [candle.high for candle in candles]
            lows = [candle.low for candle in candles]
            volumes = [candle.volume for candle in candles]

            ema_fast_series = calculate_ema(closes, self.settings.ema_fast_period)
            ema_slow_series = calculate_ema(closes, self.settings.ema_slow_period)
            rsi_series = calculate_rsi(closes, self.settings.rsi_period)
            vwap_series = calculate_vwap(highs, lows, closes, volumes)
            macd_line, macd_signal, macd_hist = calculate_macd(
                closes,
                self.settings.macd_fast_period,
                self.settings.macd_slow_period,
                self.settings.macd_signal_period,
            )

            if not closes:
                return None

            average_volume = None
            if len(volumes) >= self.settings.volume_lookback:
                selected_volumes = volumes[-self.settings.volume_lookback :]
                average_volume = sum(selected_volumes) / len(selected_volumes)

            average_range_pct = None
            if len(candles) >= self.settings.volume_lookback:
                selected_candles = candles[-self.settings.volume_lookback :]
                valid_candles = [candle for candle in selected_candles if candle.close > 0]
                if valid_candles:
                    average_range_pct = sum(
                        ((candle.high - candle.low) / candle.close) * 100 for candle in valid_candles
                    ) / len(valid_candles)

            snapshot.timeframes[timeframe] = TimeframeIndicatorSnapshot(
                ema_fast=ema_fast_series[-1],
                ema_slow=ema_slow_series[-1],
                rsi=rsi_series[-1],
                vwap=vwap_series[-1] if vwap_series else None,
                macd=macd_line[-1],
                macd_signal=macd_signal[-1],
                macd_hist=macd_hist[-1],
                latest_close=closes[-1],
                previous_close=closes[-2] if len(closes) >= 2 else None,
                latest_volume=volumes[-1] if volumes else None,
                average_volume=average_volume,
                average_range_pct=average_range_pct,
            )

        return snapshot

    def _can_emit_signal(self, signal: CandidateSignal) -> bool:
        now = signal.generated_at

        for existing in self._signals:
            age = now - existing.generated_at
            if age > timedelta(minutes=5):
                continue

            if existing.symbol == signal.symbol and age <= timedelta(minutes=2):
                return False

            if (
                existing.symbol == signal.symbol
                and existing.strategy_name == signal.strategy_name
                and existing.side == signal.side
                and age <= timedelta(minutes=5)
            ):
                return False

        return True

    def _store_signal(self, signal: CandidateSignal) -> None:
        self._signals.insert(0, signal)
        self._signals = self._signals[: self.settings.signals_store_limit]
        if self.signals_repo is not None:
            self.signals_repo.upsert_signal(signal)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="signal_generated",
                entity_id=signal.signal_id,
                symbol=signal.symbol,
                payload={
                    "strategy_name": signal.strategy_name,
                    "confidence_score": signal.confidence_score,
                    "side": signal.side,
                },
            )
        log_structured_event(
            logger,
            "signal_generated",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            strategy_name=signal.strategy_name,
            confidence_score=signal.confidence_score,
        )

    async def _maybe_await(self, value: object) -> object:
        if inspect.isawaitable(value):
            return await value
        return value

    def _default_signal_id_factory(
        self,
        symbol: str,
        strategy_name: str,
        side: str,
        generated_at: datetime,
    ) -> str:
        seed = "|".join(
            [
                symbol.upper(),
                strategy_name,
                side.lower(),
                generated_at.astimezone(timezone.utc).isoformat(),
            ]
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        return f"sig_{digest[:12]}"

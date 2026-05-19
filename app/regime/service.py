from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Callable

from app.alpha_fusion.types import AlphaFeatureSnapshot
from app.config.settings import Settings, get_settings
from app.features.service import FeatureService
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.regime_repo import RegimeRepository

from app.regime.types import RegimeSnapshot

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


class RegimeService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        feature_service: FeatureService | None = None,
        regime_repo: RegimeRepository | None = None,
        events_repo: EventsRepository | None = None,
        time_provider: Callable[[], datetime] | None = None,
        snapshot_id_factory: Callable[[str, datetime], str] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.feature_service = feature_service
        self.regime_repo = regime_repo
        self.events_repo = events_repo
        self.time_provider = time_provider or utc_now
        self.snapshot_id_factory = snapshot_id_factory or self._default_snapshot_id_factory

    async def evaluate_symbol(
        self,
        symbol: str,
        *,
        feature_snapshot: AlphaFeatureSnapshot | None = None,
        generated_at: datetime | None = None,
    ) -> RegimeSnapshot | None:
        snapshot = feature_snapshot
        if snapshot is None:
            if self.feature_service is None:
                return None
            feature_run = await self.feature_service.compute_symbol(symbol, generated_at=generated_at, persist=True)
            if feature_run is None or feature_run.feature_snapshot is None:
                return None
            snapshot = feature_run.feature_snapshot

        run_time = generated_at or self.time_provider()
        regime = self.classify_snapshot(snapshot, generated_at=run_time)
        self._store_snapshot(regime)
        return regime

    def classify_snapshot(
        self,
        snapshot: AlphaFeatureSnapshot,
        *,
        generated_at: datetime | None = None,
    ) -> RegimeSnapshot:
        trend_vector = snapshot.timeframes.get(snapshot.trend_timeframe)
        setup_vector = snapshot.timeframes.get(snapshot.setup_timeframe) or trend_vector
        trigger_vector = snapshot.timeframes.get(snapshot.trigger_timeframe) or setup_vector or trend_vector

        trend_strength = 0.0
        if trend_vector is not None:
            trend_strength = (
                (trend_vector.ema_gap_bps or 0.0) / 120.0
                + (trend_vector.ema_slope_bps or 0.0) / 40.0
                + (((trend_vector.macd_hist or 0.0) / max(trend_vector.latest_close, 1e-9)) * 10000 / 20.0)
            ) / 3.0

        volatility_score = 0.0
        if setup_vector is not None and setup_vector.atr_pct is not None:
            volatility_score = abs(setup_vector.atr_pct) / max(self.settings.regime_volatility_high_pct, 1e-9)

        compression_score = 0.0
        if trigger_vector is not None and trigger_vector.range_compression_pct is not None:
            compression_score = max(
                0.0,
                1.0 - (trigger_vector.range_compression_pct / max(self.settings.regime_compression_pct_threshold, 1e-9)),
            )
            if trigger_vector.squeeze_on:
                compression_score = min(1.0, compression_score + 0.2)

        mean_reversion_score = 0.0
        if trigger_vector is not None and trigger_vector.rsi is not None and abs(trigger_vector.breakout_bias) < 0.35:
            mean_reversion_score = max(0.0, 1.0 - (abs(trigger_vector.rsi - 50.0) / 25.0))

        supporting_factors: list[str] = []
        veto_factors: list[str] = []
        regime = "mean_reverting"

        if trend_strength >= self.settings.regime_trend_strength_threshold:
            regime = "trending_up"
            supporting_factors.append("trend_strength_positive")
        elif trend_strength <= -self.settings.regime_trend_strength_threshold:
            regime = "trending_down"
            supporting_factors.append("trend_strength_negative")
        elif compression_score >= 0.85:
            regime = "compressed_breakout_setup"
            supporting_factors.append("compression_detected")
        elif volatility_score >= 1.1 and abs(trend_strength) < self.settings.regime_trend_strength_threshold:
            regime = "volatile_chop"
            supporting_factors.append("volatility_dominant_without_trend")
        else:
            supporting_factors.append("mean_reversion_bias")

        if volatility_score >= self.settings.regime_risk_off_volatility_multiplier:
            regime = "risk_off"
            veto_factors.append("volatility_shock")
        if trigger_vector is not None and trigger_vector.market_structure == "expanding":
            veto_factors.append("unstable_structure")

        confidence = _clamp(
            0.45
            + min(abs(trend_strength), 1.0) * 0.25
            + min(volatility_score, 1.0) * 0.15
            + min(compression_score, 1.0) * 0.15
        )
        run_time = generated_at or self.time_provider()
        return RegimeSnapshot(
            snapshot_id=self.snapshot_id_factory(snapshot.symbol, run_time),
            symbol=snapshot.symbol,
            regime=regime,
            confidence=round(confidence, 6),
            generated_at=run_time,
            trend_score=round(trend_strength, 6),
            volatility_score=round(volatility_score, 6),
            compression_score=round(compression_score, 6),
            mean_reversion_score=round(mean_reversion_score, 6),
            supporting_factors=supporting_factors,
            veto_factors=veto_factors,
            metadata={
                "trend_timeframe": snapshot.trend_timeframe,
                "setup_timeframe": snapshot.setup_timeframe,
                "trigger_timeframe": snapshot.trigger_timeframe,
            },
        )

    def get_current(self, symbol: str) -> RegimeSnapshot | None:
        if self.regime_repo is None:
            return None
        return self.regime_repo.get_latest_snapshot(symbol.upper())

    def list_history(self, *, symbol: str | None = None, limit: int | None = None) -> list[RegimeSnapshot]:
        if self.regime_repo is None:
            return []
        return self.regime_repo.list_snapshots(symbol=symbol, limit=limit or self.settings.regime_store_limit)

    def _store_snapshot(self, snapshot: RegimeSnapshot) -> None:
        if self.regime_repo is not None:
            self.regime_repo.upsert_snapshot(snapshot)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="regime_snapshot_generated",
                entity_id=snapshot.snapshot_id,
                symbol=snapshot.symbol,
                payload={
                    "regime": snapshot.regime,
                    "confidence": snapshot.confidence,
                    "supporting_factors": snapshot.supporting_factors,
                    "veto_factors": snapshot.veto_factors,
                },
            )

    def _default_snapshot_id_factory(self, symbol: str, generated_at: datetime) -> str:
        seed = "|".join([symbol.upper(), generated_at.astimezone(timezone.utc).isoformat()])
        return f"regime_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"

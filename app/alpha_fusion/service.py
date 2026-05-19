from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Callable

from app.alpha_fusion.types import AlphaFeatureSnapshot, AlphaSourceReading, FusedAlphaSignal, FusionComponent
from app.config.settings import Settings, get_settings
from app.features.service import FeatureService
from app.persistence.repositories.alpha_fusion_repo import AlphaFusionRepository
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.feature_runs_repo import FeatureRunsRepository
from app.persistence.repositories.fused_opportunities_repo import FusedOpportunitiesRepository
from app.persistence.repositories.regime_repo import RegimeRepository
from app.regime.service import RegimeService
from app.regime.types import RegimeSnapshot
from app.signals.schemas import normalize_requested_symbols

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _signed_score(value: float | None, scale: float) -> float | None:
    if value is None or scale <= 0:
        return None
    return max(-1.0, min(1.0, value / scale))


def _component_score(norms: list[float | None]) -> float:
    usable = [0.5 + (0.5 * item) for item in norms if item is not None]
    if not usable:
        return 0.5
    return round(sum(usable) / len(usable), 6)


class AlphaFusionService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        market_data_service: object | None = None,
        feature_service: FeatureService | None = None,
        regime_service: RegimeService | None = None,
        feature_runs_repo: FeatureRunsRepository | None = None,
        source_repo: AlphaSourcesRepository | None = None,
        fused_repo: FusedOpportunitiesRepository | None = None,
        fusion_repo: AlphaFusionRepository | None = None,
        regime_repo: RegimeRepository | None = None,
        events_repo: EventsRepository | None = None,
        arbitrage_service: object | None = None,
        microstructure_service: object | None = None,
        polymarket_service: object | None = None,
        wallet_intel_service: object | None = None,
        event_signals_service: object | None = None,
        provider_health_service: object | None = None,
        mirofish_adapter: object | None = None,
        risk_service: object | None = None,
        time_provider: Callable[[], datetime] | None = None,
        signal_id_factory: Callable[[str, datetime], str] | None = None,
        source_id_factory: Callable[[str, str, datetime], str] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.market_data_service = market_data_service
        self.feature_service = feature_service or FeatureService(
            settings=self.settings,
            market_data_service=market_data_service,
            feature_runs_repo=feature_runs_repo,
            events_repo=events_repo,
        )
        self.regime_service = regime_service or RegimeService(
            settings=self.settings,
            feature_service=self.feature_service,
            regime_repo=regime_repo,
            events_repo=events_repo,
        )
        self.source_repo = source_repo
        self.fused_repo = fused_repo
        self.fusion_repo = fusion_repo
        self.events_repo = events_repo
        self.arbitrage_service = arbitrage_service
        self.microstructure_service = microstructure_service
        self.polymarket_service = polymarket_service
        self.wallet_intel_service = wallet_intel_service
        self.event_signals_service = event_signals_service
        self.provider_health_service = provider_health_service
        self.mirofish_adapter = mirofish_adapter
        self.risk_service = risk_service
        self.time_provider = time_provider or utc_now
        self.signal_id_factory = signal_id_factory or self._default_signal_id_factory
        self.source_id_factory = source_id_factory or self._default_source_id_factory
        self.supported_symbols = [symbol.upper() for symbol in self.settings.signals_supported_symbols]
        self._fused_signals: list[FusedAlphaSignal] = []

    async def evaluate_symbols(
        self,
        symbols: list[str] | None = None,
        *,
        generated_at: datetime | None = None,
    ) -> list[FusedAlphaSignal]:
        normalized_symbols = normalize_requested_symbols(symbols) or self.supported_symbols
        evaluation_time = generated_at or self.time_provider()
        fused_signals: list[FusedAlphaSignal] = []
        for symbol in normalized_symbols:
            if symbol.upper() not in self.supported_symbols:
                continue
            feature_run = await self.feature_service.compute_symbol(symbol, generated_at=evaluation_time, persist=True)
            if feature_run is None or feature_run.feature_snapshot is None:
                continue
            regime_snapshot = await self.regime_service.evaluate_symbol(
                symbol,
                feature_snapshot=feature_run.feature_snapshot,
                generated_at=evaluation_time,
            )
            if regime_snapshot is None:
                continue
            source_readings = await self._build_source_readings(
                snapshot=feature_run.feature_snapshot,
                regime_snapshot=regime_snapshot,
                generated_at=evaluation_time,
            )
            self._store_source_readings(source_readings)
            fused_signal = self._build_fused_signal(
                symbol=symbol.upper(),
                snapshot=feature_run.feature_snapshot,
                regime_snapshot=regime_snapshot,
                source_readings=source_readings,
                generated_at=evaluation_time,
            )
            self._store_signal(fused_signal)
            fused_signals.append(fused_signal)
        return fused_signals

    async def evaluate_targets(
        self,
        targets: list[str] | None = None,
        *,
        generated_at: datetime | None = None,
    ) -> list[FusedAlphaSignal]:
        evaluation_time = generated_at or self.time_provider()
        normalized_targets = [item.upper() if item.upper() in self.supported_symbols else item for item in (targets or self.supported_symbols)]
        crypto_targets = [item for item in normalized_targets if isinstance(item, str) and item.upper() in self.supported_symbols]
        fused = await self.evaluate_symbols(crypto_targets, generated_at=evaluation_time) if crypto_targets else []
        polymarket_targets = [item for item in normalized_targets if item not in crypto_targets]
        if polymarket_targets and self.polymarket_service is not None:
            for target in polymarket_targets:
                target_sources = await self._build_market_target_sources(target=target, generated_at=evaluation_time)
                if not target_sources:
                    continue
                signal = self._build_source_only_signal(target=target, source_readings=target_sources, generated_at=evaluation_time)
                self._store_source_readings(target_sources)
                self._store_signal(signal)
                fused.append(signal)
        return fused

    async def get_feature_snapshot(
        self,
        symbol: str,
        *,
        generated_at: datetime | None = None,
    ) -> AlphaFeatureSnapshot | None:
        feature_run = await self.feature_service.compute_symbol(symbol, generated_at=generated_at, persist=True)
        if feature_run is None:
            return self.feature_service.latest_snapshot(symbol)
        return feature_run.feature_snapshot

    def list_fused_signals(
        self,
        *,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[FusedAlphaSignal]:
        items = self._fused_signals
        if not items and self.fused_repo is not None:
            items = self.fused_repo.list_opportunities(
                symbol_or_market=symbol,
                limit=limit or self.settings.alpha_fusion_store_limit,
            )
        elif not items and self.fusion_repo is not None:
            items = self.fusion_repo.list_signals(symbol=symbol, limit=limit or self.settings.alpha_fusion_store_limit)
        if symbol is not None:
            items = [item for item in items if item.symbol == symbol or item.symbol == symbol.upper()]
        if limit is not None:
            items = items[: max(limit, 0)]
        return [replace(item) for item in items]

    def get_fused_signal(self, signal_id: str) -> FusedAlphaSignal | None:
        for signal in self._fused_signals:
            if signal.signal_id == signal_id:
                return replace(signal)
        if self.fused_repo is not None:
            signal = self.fused_repo.get_opportunity(signal_id)
            if signal is not None:
                self._store_signal(signal, emit_events=False)
                return replace(signal)
        if self.fusion_repo is None:
            return None
        signal = self.fusion_repo.get_signal(signal_id)
        if signal is None:
            return None
        self._store_signal(signal, emit_events=False)
        return replace(signal)

    def list_source_readings(
        self,
        *,
        symbol_or_market: str | None = None,
        source_name: str | None = None,
        limit: int | None = None,
    ) -> list[AlphaSourceReading]:
        if self.source_repo is None:
            return []
        return self.source_repo.list_readings(
            symbol_or_market=symbol_or_market,
            source_name=source_name,
            limit=limit or self.settings.alpha_source_store_limit,
        )

    def build_intelligence_summary(self, *, limit: int = 5) -> dict[str, object]:
        latest_signals = self.list_fused_signals(limit=limit)
        regimes = []
        for symbol in self.supported_symbols[:limit]:
            regime = self.regime_service.get_current(symbol)
            if regime is not None:
                regimes.append(regime)
        active_locks = []
        if self.risk_service is not None and hasattr(self.risk_service, "list_current_locks"):
            active_locks = self.risk_service.list_current_locks()
        basis_highlights = []
        if self.arbitrage_service is not None and hasattr(self.arbitrage_service, "list_opportunities"):
            basis_highlights = [
                {**asdict(item), "id": item.opportunity_id}
                for item in self.arbitrage_service.list_opportunities(limit=limit, tradable=None)
            ][:limit]
        microstructure = []
        if self.microstructure_service is not None:
            for symbol in self.supported_symbols[:limit]:
                latest = self.microstructure_service.get_latest(symbol)
                if latest is not None:
                    microstructure.append(asdict(latest))
        polymarket_highlights = []
        if self.polymarket_service is not None and hasattr(self.polymarket_service, "list_persisted_opportunities"):
            polymarket_highlights = [
                {**asdict(item), "id": item.opportunity_id}
                for item in self.polymarket_service.list_persisted_opportunities(limit=limit)
            ]
        latency_arb_highlights = []
        if hasattr(self, "latency_arb_service") and self.latency_arb_service is not None and hasattr(self.latency_arb_service, "list_opportunities"):
            latency_arb_highlights = [
                asdict(item)
                for item in self.latency_arb_service.list_opportunities(limit=limit)
            ]
        strategy_owner_summary = None
        if hasattr(self, "strategy_owner_service") and self.strategy_owner_service is not None and hasattr(self.strategy_owner_service, "build_summary"):
            strategy_owner_summary = asdict(self.strategy_owner_service.build_summary())
        wallet_highlights = []
        if self.wallet_intel_service is not None and hasattr(self.wallet_intel_service, "leaderboard"):
            wallet_highlights = [asdict(item) for item in self.wallet_intel_service.leaderboard(limit=limit)]
        event_highlights = []
        if self.event_signals_service is not None and hasattr(self.event_signals_service, "list_signals"):
            event_highlights = [asdict(item) for item in self.event_signals_service.list_signals(limit=limit)]
        provider_health = self.provider_health_service.build_summary() if self.provider_health_service is not None and hasattr(self.provider_health_service, "build_summary") else {"items": [], "count": 0}
        mirofish = self.mirofish_adapter.latest() if self.mirofish_adapter is not None and hasattr(self.mirofish_adapter, "latest") else None
        promotion_blockers = []
        if hasattr(self, "promotion_service") and self.promotion_service is not None and hasattr(self.promotion_service, "list_status"):
            promotion_blockers = [
                {
                    "strategy_name": item.strategy_name,
                    "current_stage": item.current_stage,
                    "explanation": item.promotion_explanation,
                }
                for item in self.promotion_service.list_status()
                if not item.eligible_for_promotion
            ][:limit]
        allocation_snapshot = None
        if hasattr(self, "portfolio_brain_service") and self.portfolio_brain_service is not None and hasattr(self.portfolio_brain_service, "get_current"):
            current = self.portfolio_brain_service.get_current()
            if current is not None:
                allocation_snapshot = asdict(current)
        incident_summary = {"count": 0, "open": 0, "acknowledged": 0}
        if hasattr(self, "openclaw_bridge") and self.openclaw_bridge is not None and hasattr(self.openclaw_bridge, "list_incidents"):
            incidents = self.openclaw_bridge.list_incidents(limit=100)
            incident_summary = {
                "count": len(incidents),
                "open": len([item for item in incidents if item.get("status") == "open"]),
                "acknowledged": len([item for item in incidents if item.get("status") == "acknowledged"]),
            }
        backfill_status = {"count": 0, "failed": 0, "running": 0, "completed": 0}
        if hasattr(self, "research_service") and self.research_service is not None and hasattr(self.research_service, "summarize_backfill_status"):
            backfill_status = self.research_service.summarize_backfill_status()
        unhealthy_providers = [
            item.provider_name
            for item in provider_health.get("items", [])
            if getattr(item, "status", None) == "unhealthy"
        ]
        return {
            "supported_symbols": list(self.supported_symbols),
            "latest_fused_opportunities": [asdict(signal) for signal in latest_signals],
            "current_regimes": [asdict(regime) for regime in regimes],
            "feature_catalog_size": len(self.feature_service.get_catalog()),
            "active_risk_locks": active_locks,
            "basis_funding_highlights": basis_highlights,
            "microstructure_status": microstructure,
            "polymarket_highlights": polymarket_highlights,
            "latency_arb_highlights": latency_arb_highlights,
            "wallet_highlights": wallet_highlights,
            "event_highlights": event_highlights,
            "strategy_owner_summary": strategy_owner_summary,
            "provider_health": provider_health,
            "mirofish_latest": asdict(mirofish) if mirofish is not None else None,
            "tradability_state": {
                "has_active_locks": bool(active_locks),
                "tradable_symbols": [item["symbol"] for item in basis_highlights if item.get("tradable")],
                "active_unhealthy_providers": unhealthy_providers,
            },
            "safe_mode": {
                "enable_live_trading": self.settings.enable_live_trading,
                "live_trading_armed": self.settings.live_trading_armed,
                "execution_mode": self.settings.execution_mode,
            },
            "promotion_blockers": promotion_blockers,
            "allocation_snapshot": allocation_snapshot,
            "incident_summary": incident_summary,
            "backfill_status": backfill_status,
        }

    async def _build_source_readings(
        self,
        *,
        snapshot: AlphaFeatureSnapshot,
        regime_snapshot: RegimeSnapshot,
        generated_at: datetime,
    ) -> list[AlphaSourceReading]:
        technical_direction = "neutral"
        if snapshot.bullish_timeframes and len(snapshot.bullish_timeframes) >= len(snapshot.bearish_timeframes):
            technical_direction = "long"
        elif snapshot.bearish_timeframes:
            technical_direction = "short"

        technical_confidence = round(
            _clamp(
                0.45
                + (snapshot.feature_coverage * 0.2)
                + (len(snapshot.bullish_timeframes) / max(len(snapshot.timeframes), 1)) * 0.2
            ),
            6,
        )

        sources = [
            AlphaSourceReading(
                reading_id=self.source_id_factory(snapshot.symbol, "technical_features", generated_at),
                source_name="technical_features",
                symbol_or_market=snapshot.symbol,
                direction=technical_direction,
                confidence=technical_confidence,
                expected_holding_period="intra-day",
                strategy_family="binance_features",
                raw_signal={
                    "bullish_timeframes": snapshot.bullish_timeframes,
                    "bearish_timeframes": snapshot.bearish_timeframes,
                },
                metadata={"feature_coverage": snapshot.feature_coverage},
                timestamp=generated_at,
            ),
            AlphaSourceReading(
                reading_id=self.source_id_factory(snapshot.symbol, "regime_engine", generated_at),
                source_name="regime_engine",
                symbol_or_market=snapshot.symbol,
                direction=self._direction_from_regime(regime_snapshot.regime),
                confidence=regime_snapshot.confidence,
                expected_holding_period="session",
                strategy_family="regime_overlay",
                raw_signal={
                    "regime": regime_snapshot.regime,
                    "trend_score": regime_snapshot.trend_score,
                },
                metadata={
                    "supporting_factors": regime_snapshot.supporting_factors,
                    "veto_factors": regime_snapshot.veto_factors,
                },
                timestamp=generated_at,
            ),
        ]
        if self.arbitrage_service is not None and hasattr(self.arbitrage_service, "as_source_reading"):
            arbitrage_source = await self._maybe_await(
                self.arbitrage_service.as_source_reading(snapshot.symbol, generated_at=generated_at)
            )
            if arbitrage_source is not None:
                sources.append(arbitrage_source)
        if self.microstructure_service is not None and hasattr(self.microstructure_service, "as_source_reading"):
            microstructure_source = await self._maybe_await(
                self.microstructure_service.as_source_reading(snapshot.symbol, generated_at=generated_at)
            )
            if microstructure_source is not None:
                sources.append(microstructure_source)
        if self.wallet_intel_service is not None and hasattr(self.wallet_intel_service, "as_source_readings"):
            wallet_sources = await self._maybe_await(self.wallet_intel_service.as_source_readings())
            sources.extend([item for item in wallet_sources if item.symbol_or_market == snapshot.symbol])
        if self.event_signals_service is not None and hasattr(self.event_signals_service, "as_source_readings"):
            event_sources = await self._maybe_await(self.event_signals_service.as_source_readings())
            sources.extend([item for item in event_sources if item.symbol_or_market == snapshot.symbol])
        if self.mirofish_adapter is not None and hasattr(self.mirofish_adapter, "run"):
            event_bias = self._directional_bias([item for item in sources if item.source_name == "event_signals"])
            wallet_bias = self._directional_bias([item for item in sources if item.source_name == "wallet_intelligence"])
            polymarket_bias = self._directional_bias([item for item in sources if item.source_name == "polymarket_mispricing"])
            mirofish_summary = self.mirofish_adapter.run(
                symbol_or_market=snapshot.symbol,
                payload={
                    "trend_score": self._signed_component_from_snapshot(snapshot),
                    "event_bias": event_bias,
                    "wallet_bias": wallet_bias,
                    "polymarket_bias": polymarket_bias,
                },
            )
            if hasattr(self.mirofish_adapter, "as_source_reading"):
                sources.append(self.mirofish_adapter.as_source_reading(mirofish_summary))
        return sources

    def _build_fused_signal(
        self,
        *,
        symbol: str,
        snapshot: AlphaFeatureSnapshot,
        regime_snapshot: RegimeSnapshot,
        source_readings: list[AlphaSourceReading],
        generated_at: datetime,
    ) -> FusedAlphaSignal:
        trend_score, trend_explanation = self._score_trend(snapshot)
        momentum_score, momentum_explanation = self._score_momentum(snapshot)
        breakout_score, breakout_explanation = self._score_breakout(snapshot)
        volatility_score, volatility_explanation = self._score_volatility(snapshot, trend_score=trend_score)
        regime_score, regime_explanation = self._score_regime(regime_snapshot)
        basis_score, basis_explanation = self._score_optional_source(source_readings, "basis_funding")
        microstructure_score, microstructure_explanation = self._score_optional_source(source_readings, "binance_microstructure")
        wallet_score, wallet_explanation = self._score_optional_source(source_readings, "wallet_intelligence")
        event_score, event_explanation = self._score_optional_source(source_readings, "event_signals")
        mirofish_score, mirofish_explanation = self._score_optional_source(source_readings, "mirofish_simulation")

        components = [
            self._component("trend", trend_score, self.settings.alpha_weight_trend, trend_explanation),
            self._component("momentum", momentum_score, self.settings.alpha_weight_momentum, momentum_explanation),
            self._component("breakout", breakout_score, self.settings.alpha_weight_breakout, breakout_explanation),
            self._component("volatility", volatility_score, self.settings.alpha_weight_volatility, volatility_explanation),
            self._component("regime", regime_score, self.settings.alpha_weight_regime, regime_explanation),
            self._component(
                "arbitrage",
                basis_score,
                self.settings.alpha_weight_arbitrage,
                basis_explanation,
            ),
            self._component(
                "microstructure",
                microstructure_score,
                self.settings.alpha_weight_microstructure,
                microstructure_explanation,
            ),
            self._component(
                "wallet_intelligence",
                wallet_score,
                self.settings.fusion_weight_wallet,
                wallet_explanation,
            ),
            self._component(
                "event_signals",
                event_score,
                self.settings.fusion_weight_event,
                event_explanation,
            ),
            self._component(
                "mirofish_simulation",
                mirofish_score,
                self.settings.fusion_weight_mirofish,
                mirofish_explanation,
            ),
        ]

        weighted_score = round(
            sum(item.score * item.weight for item in components) / max(sum(item.weight for item in components), 1e-9),
            6,
        )
        direction = "neutral"
        if weighted_score >= self.settings.alpha_long_threshold:
            direction = "long"
        elif weighted_score <= 1.0 - self.settings.alpha_short_threshold:
            direction = "short"

        aligned_count = 0
        directional_components = [
            item for item in components if item.name in {"trend", "momentum", "breakout", "volatility", "regime"}
        ]
        if direction == "long":
            aligned_count = sum(1 for item in directional_components if item.score > 0.55)
        elif direction == "short":
            aligned_count = sum(1 for item in directional_components if item.score < 0.45)
        else:
            aligned_count = sum(1 for item in directional_components if 0.45 <= item.score <= 0.55)

        alignment = aligned_count / max(len(directional_components), 1)
        confidence = round(
            _clamp(
                (abs(weighted_score - 0.5) * 1.6)
                + (snapshot.feature_coverage * 0.18)
                + (alignment * 0.2)
                + (regime_snapshot.confidence * 0.08)
            ),
            6,
        )
        supporting_factors = [
            item.explanation for item in components if (direction == "long" and item.score > 0.55) or (direction == "short" and item.score < 0.45)
        ]
        supporting_factors.extend(regime_snapshot.supporting_factors)
        veto_factors = list(regime_snapshot.veto_factors)
        veto_factors.extend(self._provider_health_veto())
        veto_factors.extend(self._source_conflict_veto(source_readings))
        explanation = self._build_explanations(
            snapshot=snapshot,
            direction=direction,
            components=components,
            regime_snapshot=regime_snapshot,
        )
        tradable = not veto_factors and direction != "neutral"
        return FusedAlphaSignal(
            signal_id=self.signal_id_factory(symbol, generated_at),
            symbol=symbol,
            score=weighted_score,
            direction=direction,
            confidence=confidence,
            explanation=explanation,
            supporting_factors=supporting_factors[:6],
            veto_factors=veto_factors[:6],
            components=components,
            feature_snapshot=snapshot,
            generated_at=generated_at,
            confidence_band=self._confidence_band(confidence),
            strategy_family="multi_source_phase3",
            status="candidate",
            regime=regime_snapshot.regime,
            tradable=tradable,
            expected_holding_period=self._derive_holding_period(source_readings),
            source_breakdown={component.name: component.score for component in components},
            metadata={"source_readings": source_readings},
        )

    def _build_source_only_signal(
        self,
        *,
        target: str,
        source_readings: list[AlphaSourceReading],
        generated_at: datetime,
    ) -> FusedAlphaSignal:
        neutral_snapshot = self._neutral_feature_snapshot(target, generated_at)
        neutral_regime = RegimeSnapshot(
            snapshot_id=f"reg_{target}",
            symbol=target,
            regime="mean_reverting",
            confidence=0.5,
            generated_at=generated_at,
            trend_score=0.0,
            volatility_score=0.0,
            compression_score=0.0,
            mean_reversion_score=0.5,
            supporting_factors=[],
            veto_factors=[],
        )
        components = []
        for source_name, weight in [
            ("polymarket_mispricing", self.settings.fusion_weight_polymarket),
            ("wallet_intelligence", self.settings.fusion_weight_wallet),
            ("event_signals", self.settings.fusion_weight_event),
            ("mirofish_simulation", self.settings.fusion_weight_mirofish),
        ]:
            score, explanation = self._score_optional_source(source_readings, source_name)
            components.append(self._component(source_name, score, weight, explanation))
        weighted_score = round(sum(item.score * item.weight for item in components) / max(sum(item.weight for item in components), 1e-9), 6)
        direction = "neutral"
        if weighted_score >= self.settings.alpha_long_threshold:
            direction = "long"
        elif weighted_score <= 1.0 - self.settings.alpha_short_threshold:
            direction = "short"
        confidence = round(_clamp((abs(weighted_score - 0.5) * 1.7) + 0.25), 6)
        veto_factors = self._provider_health_veto()
        return FusedAlphaSignal(
            signal_id=self.signal_id_factory(target, generated_at),
            symbol=target,
            score=weighted_score,
            direction=direction,
            confidence=confidence,
            explanation=[f"Source-only fusion for {target}."],
            supporting_factors=[item.explanation for item in components if abs(item.score - 0.5) > 0.08],
            veto_factors=veto_factors,
            components=components,
            feature_snapshot=neutral_snapshot,
            generated_at=generated_at,
            confidence_band=self._confidence_band(confidence),
            strategy_family="prediction_market_phase3",
            status="candidate",
            regime=neutral_regime.regime,
            tradable=not veto_factors and direction != "neutral",
            expected_holding_period=self._derive_holding_period(source_readings),
            source_breakdown={component.name: component.score for component in components},
            metadata={"source_readings": source_readings},
        )

    def _component(self, name: str, score: float, weight: float, explanation: str) -> FusionComponent:
        state = "neutral"
        if score > 0.55:
            state = "bullish"
        elif score < 0.45:
            state = "bearish"
        return FusionComponent(
            name=name,
            score=round(score, 6),
            weight=round(weight, 6),
            contribution=round(score * weight, 6),
            state=state,
            explanation=explanation,
        )

    def _score_trend(self, snapshot: AlphaFeatureSnapshot) -> tuple[float, str]:
        vector = snapshot.timeframes.get(snapshot.trend_timeframe)
        if vector is None:
            return 0.5, f"Trend timeframe {snapshot.trend_timeframe} is unavailable; component stays neutral."
        score = _component_score(
            [
                _signed_score(vector.ema_gap_bps, 60.0),
                _signed_score(vector.ema_slope_bps, 25.0),
                _signed_score(vector.vwap_gap_bps, 75.0),
                _signed_score(((vector.macd_hist or 0.0) / vector.latest_close) * 10000, 20.0),
            ]
        )
        return (
            score,
            (
                f"{snapshot.trend_timeframe} trend is {vector.trend_state}: "
                f"EMA gap={vector.ema_gap_bps}, EMA slope={vector.ema_slope_bps}, VWAP gap={vector.vwap_gap_bps}."
            ),
        )

    def _score_momentum(self, snapshot: AlphaFeatureSnapshot) -> tuple[float, str]:
        vectors = [
            snapshot.timeframes.get(snapshot.setup_timeframe),
            snapshot.timeframes.get(snapshot.trigger_timeframe),
        ]
        usable = [item for item in vectors if item is not None]
        if not usable:
            return 0.5, "Momentum inputs are unavailable; component stays neutral."

        norms: list[float | None] = []
        for vector in usable:
            rsi_norm = None if vector.rsi is None else max(-1.0, min(1.0, (vector.rsi - 50.0) / 25.0))
            ret_1_norm = _signed_score(vector.return_1_pct, 0.8)
            ret_3_norm = _signed_score(vector.return_3_pct, 1.5)
            macd_norm = _signed_score(((vector.macd_hist or 0.0) / vector.latest_close) * 10000, 18.0)
            norms.extend([rsi_norm, ret_1_norm, ret_3_norm, macd_norm])

        score = _component_score(norms)
        trigger = snapshot.timeframes.get(snapshot.trigger_timeframe)
        return (
            score,
            (
                f"Momentum uses {snapshot.setup_timeframe} and {snapshot.trigger_timeframe}: "
                f"trigger RSI={trigger.rsi if trigger else None}, trigger return_3_pct={trigger.return_3_pct if trigger else None}."
            ),
        )

    def _score_breakout(self, snapshot: AlphaFeatureSnapshot) -> tuple[float, str]:
        vector = snapshot.timeframes.get(snapshot.trigger_timeframe)
        if vector is None:
            return 0.5, f"Breakout timeframe {snapshot.trigger_timeframe} is unavailable; component stays neutral."

        pressure_norm = None
        if vector.breakout_up_distance_pct is not None and vector.breakout_down_distance_pct is not None:
            pressure_norm = _signed_score(vector.breakout_down_distance_pct - vector.breakout_up_distance_pct, 4.0)
        volume_norm = None
        if vector.volume_ratio is not None:
            volume_norm = max(-1.0, min(1.0, (vector.volume_ratio - 1.0) / 1.0))
        compression_norm = None
        if vector.range_compression_pct is not None:
            compression_norm = _signed_score(self.settings.regime_compression_pct_threshold - vector.range_compression_pct, 2.0)

        score = _component_score([vector.breakout_bias, pressure_norm, volume_norm, compression_norm])
        return (
            score,
            (
                f"Breakout pressure on {snapshot.trigger_timeframe}: bias={vector.breakout_bias}, "
                f"compression={vector.range_compression_pct}, volume_ratio={vector.volume_ratio}, squeeze_on={vector.squeeze_on}."
            ),
        )

    def _score_volatility(self, snapshot: AlphaFeatureSnapshot, *, trend_score: float) -> tuple[float, str]:
        vector = snapshot.timeframes.get(snapshot.setup_timeframe) or snapshot.timeframes.get(snapshot.trigger_timeframe)
        if vector is None or vector.atr_pct is None:
            return 0.5, "Volatility input is unavailable; component stays neutral."

        atr_pct = abs(vector.atr_pct)
        tradability = 1.0 - min(
            1.0,
            abs(atr_pct - self.settings.alpha_target_atr_pct) / max(self.settings.alpha_target_atr_pct, 1e-9),
        )
        squeeze_bonus = 0.05 if vector.squeeze_on else 0.0
        direction_bias = (trend_score - 0.5) * 2
        score = _clamp(0.5 + (direction_bias * max(tradability - 0.25, 0.0) * 0.4) + squeeze_bonus)
        return (
            round(score, 6),
            (
                f"ATR regime on {vector.timeframe}: atr_pct={vector.atr_pct}, "
                f"target_atr_pct={self.settings.alpha_target_atr_pct}, squeeze_on={vector.squeeze_on}."
            ),
        )

    def _score_regime(self, regime_snapshot: RegimeSnapshot) -> tuple[float, str]:
        score_map = {
            "trending_up": 0.72,
            "compressed_breakout_setup": 0.63,
            "mean_reverting": 0.5,
            "volatile_chop": 0.42,
            "trending_down": 0.28,
            "risk_off": 0.35,
        }
        score = score_map.get(regime_snapshot.regime, 0.5)
        return (
            score,
            (
                f"Regime overlay classified {regime_snapshot.symbol} as {regime_snapshot.regime} "
                f"with confidence={regime_snapshot.confidence}."
            ),
        )

    def _score_optional_source(self, source_readings: list[AlphaSourceReading], source_name: str) -> tuple[float, str]:
        relevant = [item for item in source_readings if item.source_name == source_name]
        reading = relevant[0] if relevant else None
        if reading is None:
            return 0.5, f"{source_name} is unavailable; component stays neutral."
        direction_score = 0.5 + (self._directional_bias(relevant) * 0.35)
        return (
            max(0.0, min(1.0, direction_score)),
            f"{source_name} count={len(relevant)} bias={round(self._directional_bias(relevant), 4)}.",
        )

    def _build_explanations(
        self,
        *,
        snapshot: AlphaFeatureSnapshot,
        direction: str,
        components: list[FusionComponent],
        regime_snapshot: RegimeSnapshot,
    ) -> list[str]:
        ordered = sorted(components, key=lambda item: abs(item.score - 0.5), reverse=True)
        explanation = [
            f"Alpha fusion evaluated {snapshot.symbol} with {round(snapshot.feature_coverage * 100, 1)}% feature coverage.",
            f"Directional outcome is {direction}; regime overlay={regime_snapshot.regime}.",
        ]
        for item in ordered[:3]:
            explanation.append(f"{item.name}: {item.explanation}")
        return explanation

    def _store_source_readings(self, readings: list[AlphaSourceReading]) -> None:
        if self.source_repo is not None:
            for reading in readings:
                self.source_repo.upsert_reading(reading)

    def _store_signal(self, signal: FusedAlphaSignal, *, emit_events: bool = True) -> None:
        self._fused_signals = [item for item in self._fused_signals if item.signal_id != signal.signal_id]
        self._fused_signals.insert(0, signal)
        self._fused_signals = self._fused_signals[: self.settings.alpha_fusion_store_limit]
        if self.fused_repo is not None:
            self.fused_repo.upsert_opportunity(signal)
        if self.fusion_repo is not None:
            self.fusion_repo.upsert_signal(signal)
        if emit_events and self.events_repo is not None:
            self.events_repo.append_event(
                event_type="alpha_fusion_generated",
                entity_id=signal.signal_id,
                symbol=signal.symbol,
                payload={
                    "score": signal.score,
                    "direction": signal.direction,
                    "confidence": signal.confidence,
                    "confidence_band": signal.confidence_band,
                    "regime": signal.regime,
                    "components": [asdict(component) for component in signal.components],
                },
            )

    def _confidence_band(self, confidence: float) -> str:
        if confidence >= 0.78:
            return "high"
        if confidence >= 0.58:
            return "medium"
        return "low"

    def _direction_from_regime(self, regime: str) -> str:
        if regime == "trending_up":
            return "long"
        if regime == "trending_down":
            return "short"
        return "neutral"

    def _default_signal_id_factory(self, symbol: str, generated_at: datetime) -> str:
        seed = "|".join([symbol.upper(), generated_at.astimezone(timezone.utc).isoformat()])
        return f"alpha_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"

    def _default_source_id_factory(self, symbol: str, source_name: str, generated_at: datetime) -> str:
        seed = "|".join([symbol.upper(), source_name, generated_at.astimezone(timezone.utc).isoformat()])
        return f"source_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"

    async def _build_polymarket_source_readings(self) -> list[AlphaSourceReading]:
        if self.polymarket_service is None or not hasattr(self.polymarket_service, "as_source_readings"):
            return []
        return await self._maybe_await(self.polymarket_service.as_source_readings())

    async def _build_market_target_sources(
        self,
        *,
        target: str,
        generated_at: datetime,
    ) -> list[AlphaSourceReading]:
        sources = [item for item in await self._build_polymarket_source_readings() if item.symbol_or_market == target]
        if self.wallet_intel_service is not None and hasattr(self.wallet_intel_service, "as_source_readings"):
            wallet_sources = await self._maybe_await(self.wallet_intel_service.as_source_readings())
            sources.extend([item for item in wallet_sources if item.symbol_or_market == target])
        if self.event_signals_service is not None and hasattr(self.event_signals_service, "as_source_readings"):
            event_sources = await self._maybe_await(self.event_signals_service.as_source_readings())
            sources.extend([item for item in event_sources if item.symbol_or_market == target])
        if self.mirofish_adapter is not None and hasattr(self.mirofish_adapter, "run"):
            mirofish_summary = self.mirofish_adapter.run(
                symbol_or_market=target,
                payload={
                    "trend_score": 0.0,
                    "event_bias": self._directional_bias([item for item in sources if item.source_name == "event_signals"]),
                    "wallet_bias": self._directional_bias([item for item in sources if item.source_name == "wallet_intelligence"]),
                    "polymarket_bias": self._directional_bias([item for item in sources if item.source_name == "polymarket_mispricing"]),
                },
            )
            if hasattr(self.mirofish_adapter, "as_source_reading"):
                sources.append(self.mirofish_adapter.as_source_reading(mirofish_summary))
        return sources

    def _neutral_feature_snapshot(self, symbol: str, generated_at: datetime) -> AlphaFeatureSnapshot:
        return AlphaFeatureSnapshot(
            symbol=symbol,
            generated_at=generated_at,
            source="synthetic_phase3",
            trend_timeframe="1h",
            setup_timeframe="15m",
            trigger_timeframe="5m",
            market_price=None,
            feature_coverage=0.0,
            bullish_timeframes=[],
            bearish_timeframes=[],
            timeframes={},
        )

    def _directional_bias(self, readings: list[AlphaSourceReading]) -> float:
        if not readings:
            return 0.0
        score = 0.0
        for item in readings:
            if item.direction == "long":
                score += item.confidence
            elif item.direction == "short":
                score -= item.confidence
        return max(-1.0, min(1.0, score / len(readings)))

    def _signed_component_from_snapshot(self, snapshot: AlphaFeatureSnapshot) -> float:
        vector = snapshot.timeframes.get(snapshot.trigger_timeframe)
        if vector is None:
            return 0.0
        return max(-1.0, min(1.0, (vector.breakout_bias or 0.0)))

    def _provider_health_veto(self) -> list[str]:
        if not self.settings.enable_provider_health_veto or self.provider_health_service is None or not hasattr(self.provider_health_service, "any_unhealthy"):
            return []
        return ["provider_unhealthy_veto"] if self.provider_health_service.any_unhealthy() else []

    def _source_conflict_veto(self, source_readings: list[AlphaSourceReading]) -> list[str]:
        wallet_bias = self._directional_bias([item for item in source_readings if item.source_name == "wallet_intelligence"])
        event_bias = self._directional_bias([item for item in source_readings if item.source_name == "event_signals"])
        if wallet_bias * event_bias < -0.05:
            return ["conflicting_wallet_event_signals"]
        return []

    def _derive_holding_period(self, source_readings: list[AlphaSourceReading]) -> str:
        periods = [item.expected_holding_period for item in source_readings if item.expected_holding_period]
        return periods[0] if periods else "intra-day"

    async def _maybe_await(self, value: object) -> object:
        if hasattr(value, "__await__"):
            return await value
        return value

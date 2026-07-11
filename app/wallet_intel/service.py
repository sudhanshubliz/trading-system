from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Protocol

from app.alpha_fusion.types import AlphaSourceReading
from app.config.settings import Settings, get_settings
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.wallet_repo import WalletRepository
from app.provider_health.service import ProviderHealthService
from app.provider_health.types import ProviderIngestRun
from app.wallet_intel.providers import (
    MockWalletProvider as BaseMockWalletProvider,
    RealWalletProvider as BaseRealWalletProvider,
    build_wallet_provider,
)
from app.wallet_intel.types import WalletObservation, WalletProfile, WalletSignal


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WalletProvider(Protocol):
    async def list_wallets(self) -> list[str]: ...
    async def get_wallet_profile(self, wallet_id: str) -> dict[str, object] | None: ...
    async def get_wallet_positions(self, wallet_id: str) -> list[dict[str, object]]: ...
    async def get_wallet_trade_history(self, wallet_id: str) -> list[dict[str, object]]: ...
    async def get_wallet_activity_window(self, wallet_id: str) -> list[dict[str, object]]: ...
    async def health_check(self) -> dict[str, object]: ...


class MockWalletProvider(BaseMockWalletProvider):
    pass


class RealWalletProvider(BaseRealWalletProvider):
    pass


class WalletIntelService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        provider: WalletProvider | None = None,
        repo: WalletRepository | None = None,
        source_repo: AlphaSourcesRepository | None = None,
        events_repo: EventsRepository | None = None,
        provider_health_service: ProviderHealthService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or build_wallet_provider(
            settings=self.settings,
            mock_provider=MockWalletProvider(),
        )
        self.repo = repo
        self.source_repo = source_repo
        self.events_repo = events_repo
        self.provider_health_service = provider_health_service
        self._profiles: OrderedDict[str, WalletProfile] = OrderedDict()
        self._signals: OrderedDict[str, WalletSignal] = OrderedDict()
        self._observations: OrderedDict[str, WalletObservation] = OrderedDict()

    async def refresh(self) -> None:
        requested_at = utc_now()
        wallet_ids: list[str] = []
        notes: list[str] = []
        status = "completed"
        try:
            wallet_ids = [self._normalize_wallet_id(item) for item in await self.provider.list_wallets()]
            for wallet_id in wallet_ids:
                profile = await self._build_profile(wallet_id)
                if profile is not None:
                    self._profiles[wallet_id] = profile
                    if self.repo is not None:
                        self.repo.upsert_profile(profile)
                    for observation in await self._build_observations(wallet_id):
                        self._store_observation(observation)
                    signal = self._build_signal(profile)
                    if signal is not None:
                        self._store_signal(signal)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            raise
        finally:
            if self.provider_health_service is not None:
                await self.provider_health_service.evaluate_provider("wallet_intel", self.provider)
                self.provider_health_service.record_ingest_run(
                    ProviderIngestRun(
                        run_id=self._build_id("wallet_intel_refresh", "ingest", requested_at),
                        provider_name="wallet_intel",
                        dataset_type="wallet_profiles",
                        requested_at=requested_at,
                        completed_at=utc_now(),
                        status=status,
                        records_requested=len(wallet_ids),
                        records_written=len(wallet_ids),
                        error_summary="; ".join(notes) if notes else None,
                        notes=notes,
                        metadata={"provider_mode": getattr(self.settings, "wallet_provider_mode", "mock")},
                    )
                )

    async def list_wallets(self) -> list[WalletProfile]:
        if not self._profiles:
            await self.refresh()
        return list(self._profiles.values()) if self._profiles else (self.repo.list_profiles() if self.repo is not None else [])

    async def get_wallet(self, wallet_id: str) -> WalletProfile | None:
        if wallet_id in self._profiles:
            return self._profiles[wallet_id]
        if not self._profiles:
            await self.refresh()
        if wallet_id in self._profiles:
            return self._profiles[wallet_id]
        return self.repo.get_profile(wallet_id) if self.repo is not None else None

    def leaderboard(self, *, mode: str = "recent_quality", limit: int = 20) -> list[WalletProfile]:
        items = list(self._profiles.values()) if self._profiles else (self.repo.list_profiles() if self.repo is not None else [])
        if mode == "crowded":
            items.sort(key=lambda item: item.crowding_score, reverse=True)
        elif mode == "high_conviction":
            items.sort(key=lambda item: (item.quality_score, item.timing_score), reverse=True)
        else:
            items.sort(key=lambda item: item.quality_score, reverse=True)
        return items[:limit]

    def list_observations(self, *, wallet_id: str | None = None, limit: int = 100) -> list[WalletObservation]:
        if self.repo is not None:
            return self.repo.list_observations(wallet_id=wallet_id, limit=limit)
        items = list(self._observations.values())
        if wallet_id is not None:
            items = [item for item in items if item.wallet_id == wallet_id]
        return items[:limit]

    def list_signals(self, *, wallet_id: str | None = None, limit: int = 100) -> list[WalletSignal]:
        if self.repo is not None:
            return self.repo.list_signals(wallet_id=wallet_id, limit=limit)
        items = list(self._signals.values())
        if wallet_id is not None:
            items = [item for item in items if item.wallet_id == wallet_id]
        return items[:limit]

    async def as_source_readings(self) -> list[AlphaSourceReading]:
        if not self._signals:
            await self.refresh()
        readings: list[AlphaSourceReading] = []
        for signal in self.list_signals(limit=100):
            readings.append(
                AlphaSourceReading(
                    reading_id=f"src_{signal.signal_id}",
                    source_name="wallet_intelligence",
                    symbol_or_market=signal.symbol_or_market,
                    direction=signal.direction,
                    confidence=signal.confidence,
                    expected_holding_period="hours_to_days",
                    strategy_family="wallet_intelligence",
                    raw_signal={"recommended_action": signal.recommended_action, "wallet_id": signal.wallet_id},
                    metadata=signal.metadata,
                    timestamp=signal.timestamp,
                )
            )
        return readings

    async def get_provider_health(self) -> dict[str, object]:
        return await self.provider.health_check()

    async def _build_profile(self, wallet_id: str) -> WalletProfile | None:
        normalized_id = self._normalize_wallet_id(wallet_id)
        raw = await self.provider.get_wallet_profile(normalized_id)
        if raw is None:
            return None
        trades = await self.provider.get_wallet_trade_history(normalized_id)
        first_seen = raw.get("first_seen", utc_now())
        last_seen = raw.get("last_seen", utc_now())
        timing_score = self.score_timing_quality(trades)
        sizing_score = self.score_sizing_discipline(trades)
        persistence_score = self.score_persistence(first_seen, last_seen, len(trades))
        drawdown_score = self.score_drawdown_discipline(trades)
        specialization_score = self.score_market_specialization(trades)
        suspicious_flags = self.detect_suspicious_behavior(trades)
        concentration_score = min(1.0, len({trade.get("market") for trade in trades}) / max(len(trades), 1))
        crowding_score = self.score_crowding_risk(trades)
        quality = self.score_overall_quality(
            hit_rate=float(raw.get("hit_rate", 0.5)),
            pnl_score=float(raw.get("pnl_score", 0.5)),
            timing_score=timing_score,
            sizing_score=sizing_score,
            persistence_score=persistence_score,
            crowding_score=crowding_score,
            drawdown_score=drawdown_score,
            specialization_score=specialization_score,
        )
        return WalletProfile(
            wallet_id=normalized_id,
            provider=self.settings.wallet_provider_mode,
            first_seen=first_seen,
            last_seen=last_seen,
            market_count=len({trade.get("market") for trade in trades}),
            trade_count=len(trades),
            estimated_hit_rate=float(raw.get("hit_rate", 0.5)),
            estimated_pnl_score=float(raw.get("pnl_score", 0.5)),
            timing_score=timing_score,
            sizing_discipline_score=sizing_score,
            concentration_score=concentration_score,
            crowding_score=crowding_score,
            persistence_score=persistence_score,
            quality_score=quality,
            notes=[f"suspicious_flags={','.join(suspicious_flags)}"] if suspicious_flags else [],
            metadata={
                **(dict(raw.get("metadata", {})) if isinstance(raw.get("metadata"), dict) else {}),
                "drawdown_score": round(drawdown_score, 6),
                "specialization_score": round(specialization_score, 6),
                "suspicious_flags": suspicious_flags,
            },
        )

    async def _build_observations(self, wallet_id: str) -> list[WalletObservation]:
        normalized_id = self._normalize_wallet_id(wallet_id)
        raw_trades = await self.provider.get_wallet_trade_history(normalized_id)
        items: list[WalletObservation] = []
        for trade in raw_trades:
            timestamp = trade.get("timestamp", utc_now())
            item = WalletObservation(
                observation_id=self._build_id(normalized_id, str(trade.get("market")), timestamp),
                wallet_id=normalized_id,
                provider=self.settings.wallet_provider_mode,
                observed_at=timestamp,
                market_or_symbol=str(trade.get("market")),
                action=str(trade.get("action")),
                inferred_direction="long" if "buy" in str(trade.get("action")) else "short",
                inferred_conviction=float(trade.get("conviction", 0.5)),
                sizing_bucket=str(trade.get("size", "medium")),
                latency_seconds=float(trade.get("latency_seconds", 30.0)) if trade.get("latency_seconds") is not None else 30.0,
                associated_event=str(trade.get("associated_event")) if trade.get("associated_event") is not None else None,
                metadata=dict(trade.get("metadata", {})) if isinstance(trade.get("metadata"), dict) else {},
            )
            items.append(item)
        return items

    def _build_signal(self, profile: WalletProfile) -> WalletSignal | None:
        observations = [item for item in self._observations.values() if item.wallet_id == profile.wallet_id]
        if not observations:
            return None
        latest = observations[0]
        recommended_action = "monitor_only"
        direction = latest.inferred_direction
        suspicious_flags = list(profile.metadata.get("suspicious_flags", [])) if isinstance(profile.metadata, dict) else []
        if suspicious_flags:
            recommended_action = "ignore"
        elif profile.quality_score >= self.settings.wallet_min_quality_score and profile.crowding_score <= self.settings.wallet_max_crowding_score:
            recommended_action = "follow" if self.settings.wallet_signal_mode in {"follow", "hybrid"} else "ignore"
        elif profile.crowding_score > self.settings.wallet_max_crowding_score:
            recommended_action = "fade" if self.settings.wallet_signal_mode in {"fade", "hybrid"} else "ignore"
            direction = "short" if latest.inferred_direction == "long" else "long"
        confidence = min(1.0, 0.3 + profile.quality_score * 0.5 + latest.inferred_conviction * 0.2)
        return WalletSignal(
            signal_id=self._build_id(profile.wallet_id, latest.market_or_symbol, latest.observed_at),
            wallet_id=profile.wallet_id,
            symbol_or_market=latest.market_or_symbol,
            timestamp=latest.observed_at,
            direction=direction,
            confidence=round(confidence, 6),
            rationale=[
                f"wallet_quality={round(profile.quality_score, 4)}",
                f"crowding={round(profile.crowding_score, 4)}",
                "independent_edge_required=true",
            ],
            quality_score_snapshot=profile.quality_score,
            crowding_risk=profile.crowding_score,
            recommended_action=recommended_action,
            metadata={"provider": profile.provider, "independent_confirmation_required": True, "suspicious_flags": suspicious_flags},
        )

    def score_persistence(self, first_seen: datetime, last_seen: datetime, trade_count: int) -> float:
        age_days = max((last_seen - first_seen).days, 1)
        return min(1.0, (trade_count / 20.0) * 0.5 + min(age_days / 180.0, 1.0) * 0.5)

    def score_timing_quality(self, trades: list[dict[str, object]]) -> float:
        if not trades:
            return 0.0
        return min(1.0, sum(float(item.get("conviction", 0.5)) for item in trades) / len(trades))

    def score_sizing_discipline(self, trades: list[dict[str, object]]) -> float:
        if not trades:
            return 0.0
        buckets = [str(item.get("size", "medium")) for item in trades]
        concentration = buckets.count("large") / len(buckets)
        return max(0.0, 1.0 - concentration * 0.6)

    def score_crowding_risk(self, trades: list[dict[str, object]]) -> float:
        if not trades:
            return 0.0
        markets = [str(item.get("market")) for item in trades]
        return max(markets.count(market) for market in set(markets)) / len(markets)

    def score_drawdown_discipline(self, trades: list[dict[str, object]]) -> float:
        if not trades:
            return 0.0
        pnl_path = [float(item.get("pnl", 0.0)) for item in trades]
        running = 0.0
        peak = 0.0
        drawdown = 0.0
        for pnl in pnl_path:
            running += pnl
            peak = max(peak, running)
            drawdown = min(drawdown, running - peak)
        return max(0.0, min(1.0, 1.0 - abs(drawdown) / max(abs(peak) + 1.0, 25.0)))

    def score_market_specialization(self, trades: list[dict[str, object]]) -> float:
        if not trades:
            return 0.0
        categories = [str(item.get("market_type", item.get("market", "unknown"))).split(":")[0] for item in trades]
        dominant = max(categories.count(item) for item in set(categories))
        return dominant / len(categories)

    def detect_suspicious_behavior(self, trades: list[dict[str, object]]) -> list[str]:
        flags: list[str] = []
        if not trades:
            return flags
        large_count = len([item for item in trades if str(item.get("size", "medium")) == "large"])
        if large_count / len(trades) > 0.6:
            flags.append("oversized_repetition")
        latency_values = [float(item.get("latency_seconds", 0.0)) for item in trades if item.get("latency_seconds") is not None]
        if latency_values and min(latency_values) < 1.0:
            flags.append("suspicious_low_latency_copy")
        associated_events = [str(item.get("associated_event")) for item in trades if item.get("associated_event")]
        if associated_events and len(set(associated_events)) == 1 and len(trades) >= 8:
            flags.append("single_event_overconcentration")
        return flags

    def score_overall_quality(
        self,
        *,
        hit_rate: float,
        pnl_score: float,
        timing_score: float,
        sizing_score: float,
        persistence_score: float,
        crowding_score: float,
        drawdown_score: float,
        specialization_score: float,
    ) -> float:
        score = (
            (hit_rate * 0.2)
            + (pnl_score * 0.18)
            + (timing_score * 0.18)
            + (sizing_score * 0.12)
            + (persistence_score * 0.14)
            + (drawdown_score * 0.1)
            + (specialization_score * 0.08)
        )
        return max(0.0, min(1.0, score - crowding_score * 0.15))

    def _store_observation(self, observation: WalletObservation) -> None:
        if observation.observation_id in self._observations:
            return
        self._observations[observation.observation_id] = observation
        self._observations.move_to_end(observation.observation_id, last=False)
        if self.repo is not None:
            self.repo.append_observation(observation)

    def _store_signal(self, signal: WalletSignal) -> None:
        self._signals[signal.signal_id] = signal
        self._signals.move_to_end(signal.signal_id, last=False)
        if self.repo is not None:
            self.repo.upsert_signal(signal)
        if self.source_repo is not None:
            self.source_repo.upsert_reading(
                AlphaSourceReading(
                    reading_id=f"src_{signal.signal_id}",
                    source_name="wallet_intelligence",
                    symbol_or_market=signal.symbol_or_market,
                    direction=signal.direction,
                    confidence=signal.confidence,
                    expected_holding_period="hours_to_days",
                    strategy_family="wallet_intelligence",
                    raw_signal={"recommended_action": signal.recommended_action, "wallet_id": signal.wallet_id},
                    metadata=signal.metadata,
                    timestamp=signal.timestamp,
                )
            )
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="wallet_signal_generated",
                entity_id=signal.signal_id,
                symbol=signal.symbol_or_market if len(signal.symbol_or_market) <= 32 else None,
                payload={"wallet_id": signal.wallet_id, "action": signal.recommended_action},
            )

    def _build_id(self, wallet_id: str, market: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{wallet_id}|{market}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"wal_{digest[:12]}"

    def _normalize_wallet_id(self, wallet_id: str) -> str:
        return str(wallet_id).strip().lower()

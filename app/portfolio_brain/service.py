from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone

from app.config.settings import Settings, get_settings
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.portfolio_brain_repo import PortfolioBrainRepository
from app.portfolio_brain.types import AllocationRecommendation, PortfolioBrainSnapshot


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PortfolioBrainService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        alpha_fusion_service: object | None = None,
        risk_service: object | None = None,
        provider_health_service: object | None = None,
        promotion_service: object | None = None,
        repo: PortfolioBrainRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.alpha_fusion_service = alpha_fusion_service
        self.risk_service = risk_service
        self.provider_health_service = provider_health_service
        self.promotion_service = promotion_service
        self.repo = repo
        self.events_repo = events_repo
        self._latest_snapshot: PortfolioBrainSnapshot | None = None

    def generate_recommendations(self, *, execution_mode: str = "paper") -> PortfolioBrainSnapshot:
        fused = self.alpha_fusion_service.list_fused_signals(limit=100) if self.alpha_fusion_service is not None else []
        provider_summary = self.provider_health_service.build_summary() if self.provider_health_service is not None else {"unhealthy": 0}
        active_locks = self.risk_service.list_current_locks() if self.risk_service is not None and hasattr(self.risk_service, "list_current_locks") else []
        promotion_status = self.promotion_service.list_status() if self.promotion_service is not None and hasattr(self.promotion_service, "list_status") else []
        promotion_by_strategy = {item.strategy_name: item for item in promotion_status}

        strategy_scores: dict[str, float] = defaultdict(float)
        market_scores: dict[str, float] = defaultdict(float)
        bucket_scores: dict[str, float] = defaultdict(float)
        bucket_members: dict[str, list[str]] = defaultdict(list)
        strategy_throttles: dict[str, float] = {}
        strategy_disables: list[str] = []
        watchlist: list[str] = []
        explanations: list[str] = []
        for item in fused:
            score = max(item.score, 0.0) * max(item.confidence, 0.0)
            if provider_summary.get("unhealthy", 0):
                score *= 0.85
            status = promotion_by_strategy.get(item.strategy_family)
            if status is not None and status.current_stage == "research":
                score *= 0.7
            if status is not None and not status.eligible_for_promotion and status.current_stage in {"guarded_live", "scaled_live"}:
                strategy_disables.append(item.strategy_family)
                score = 0.0
            strategy_scores[item.strategy_family] += score
            market_scores[item.symbol] += score
            bucket = self._infer_bucket(strategy_family=item.strategy_family, symbol=item.symbol)
            bucket_scores[bucket] += score
            bucket_members[bucket].append(item.strategy_family)
            if item.veto_factors:
                watchlist.append(item.symbol)
        if active_locks:
            for lock in active_locks:
                strategy_throttles[str(lock.get("scope_key", "system"))] = 0.5

        total_strategy = sum(strategy_scores.values()) or 1.0
        total_market = sum(market_scores.values()) or 1.0
        capital_by_strategy = {
            key: round(min(self.settings.portfolio_max_strategy_weight, value / total_strategy), 6)
            for key, value in strategy_scores.items()
            if value > 0
        }
        capital_by_market = {
            key: round(min(self.settings.portfolio_max_market_weight, value / total_market), 6)
            for key, value in market_scores.items()
            if value > 0
        }
        bucket_caps = {
            "crypto_directional": self.settings.portfolio_bucket_cap_crypto_directional,
            "event_markets": self.settings.portfolio_bucket_cap_event_markets,
            "wallet_follow": self.settings.portfolio_bucket_cap_wallet_follow,
        }
        for bucket, cap in bucket_caps.items():
            current = sum(
                capital_by_strategy.get(strategy_name, 0.0)
                for strategy_name in set(bucket_members.get(bucket, []))
            )
            if current <= cap or current <= 0:
                continue
            throttle = round(cap / current, 6)
            explanations.append(f"bucket_cap_applied:{bucket} current={round(current, 6)} cap={cap}")
            for strategy_name in set(bucket_members.get(bucket, [])):
                current_weight = capital_by_strategy.get(strategy_name, 0.0)
                if current_weight <= 0:
                    continue
                capital_by_strategy[strategy_name] = round(current_weight * throttle, 6)
                strategy_throttles[strategy_name] = min(strategy_throttles.get(strategy_name, 1.0), throttle)
            for market, weight in list(capital_by_market.items()):
                if self._infer_bucket(strategy_family="market", symbol=market) == bucket:
                    capital_by_market[market] = round(weight * throttle, 6)
            watchlist.extend(bucket_members.get(bucket, []))
        snapshot = PortfolioBrainSnapshot(
            snapshot_id=self._build_id(execution_mode),
            execution_mode=execution_mode,
            generated_at=utc_now(),
            capital_by_strategy_family=capital_by_strategy,
            capital_by_symbol_or_market=capital_by_market,
            gross_exposure_cap=round(1.0 - min(len(active_locks) * 0.1, 0.5), 6),
            net_exposure_guidance=round(sum(capital_by_market.values()), 6),
            strategy_throttles=strategy_throttles,
            strategy_disables=sorted(set(strategy_disables)),
            watchlist=sorted(set(watchlist)),
            explanation=[
                f"fused_candidates={len(fused)}",
                f"active_locks={len(active_locks)}",
                f"unhealthy_providers={provider_summary.get('unhealthy', 0)}",
                *explanations,
            ],
            metadata={
                "promotion_status_count": len(promotion_status),
                "correlation_buckets": dict(bucket_scores),
                "bucket_members": {key: sorted(set(value)) for key, value in bucket_members.items()},
            },
        )
        self._latest_snapshot = snapshot
        if self.repo is not None:
            self.repo.upsert_snapshot(snapshot)
            for strategy_name, capital_pct in capital_by_strategy.items():
                self.repo.append_allocation(
                    AllocationRecommendation(
                        allocation_id=self._build_id(f"{execution_mode}:{strategy_name}"),
                        strategy_name=strategy_name,
                        scope_key=strategy_name,
                        capital_pct=capital_pct,
                        status="recommended",
                        explanation=[f"weight={capital_pct}"],
                        metadata={"generated_at": snapshot.generated_at},
                    )
                )
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="portfolio_brain_generated",
                entity_id=snapshot.snapshot_id,
                execution_mode=execution_mode,
                payload={"strategy_count": len(capital_by_strategy), "market_count": len(capital_by_market)},
            )
        return snapshot

    def get_current(self) -> PortfolioBrainSnapshot | None:
        return self._latest_snapshot

    def list_history(self, *, limit: int = 100) -> list[PortfolioBrainSnapshot]:
        if self.repo is not None:
            return self.repo.list_snapshots(limit=limit)
        return [self._latest_snapshot] if self._latest_snapshot is not None else []

    def list_allocations(self, *, limit: int = 100) -> list[AllocationRecommendation]:
        if self.repo is not None:
            return self.repo.list_allocations(limit=limit)
        if self._latest_snapshot is None:
            return []
        return [
            AllocationRecommendation(
                allocation_id=self._build_id(strategy_name),
                strategy_name=strategy_name,
                scope_key=strategy_name,
                capital_pct=value,
                status="recommended",
            )
            for strategy_name, value in self._latest_snapshot.capital_by_strategy_family.items()
        ]

    def _build_id(self, value: str) -> str:
        digest = hashlib.sha1(f"{value}|{utc_now().isoformat()}".encode("utf-8")).hexdigest()
        return f"pbr_{digest[:12]}"

    def _infer_bucket(self, *, strategy_family: str, symbol: str) -> str:
        strategy_value = strategy_family.lower()
        symbol_value = symbol.lower()
        if "wallet" in strategy_value:
            return "wallet_follow"
        if "polymarket" in strategy_value or symbol_value.startswith("pm_"):
            return "event_markets"
        if "basis" in strategy_value or "carry" in strategy_value:
            return "crypto_carry"
        if "microstructure" in strategy_value:
            return "microstructure_short_horizon"
        if "event" in strategy_value or "news" in strategy_value:
            return "news_event_reaction"
        return "crypto_directional"

from __future__ import annotations

from dataclasses import replace

from app.config.settings import Settings
from app.market_data.types import OrderBookSnapshot
from app.provider_health.service import ProviderHealthService
from app.provider_health.types import ProviderHealthSnapshot
from app.regime.service import RegimeService
from app.regime.types import RegimeSnapshot
from app.risk.service import RiskService
from app.strategy_owner.calibration import (
    clamp,
    execution_quality_score,
    historical_performance_score,
    normalize_expected_value_bps,
)
from app.strategy_owner.promotion_gate import gate_strategy
from app.strategy_owner.types import StrategyDecisionCandidate


class StrategyCandidateEvaluator:
    def __init__(
        self,
        *,
        settings: Settings,
        provider_health_service: ProviderHealthService | None = None,
        regime_service: RegimeService | None = None,
        execution_quality_service: object | None = None,
        promotion_service: object | None = None,
        risk_service: RiskService | None = None,
    ) -> None:
        self.settings = settings
        self.provider_health_service = provider_health_service
        self.regime_service = regime_service
        self.execution_quality_service = execution_quality_service
        self.promotion_service = promotion_service
        self.risk_service = risk_service

    def enrich_candidate(
        self,
        candidate: StrategyDecisionCandidate,
        *,
        provider_names: list[str],
        order_book: OrderBookSnapshot | None = None,
    ) -> StrategyDecisionCandidate:
        provider_score, provider_notes = self._provider_health_score(provider_names)
        regime_score, regime_notes = self._regime_score(candidate.symbol_or_market, candidate.direction)
        execution_score = execution_quality_score(
            self.execution_quality_service,
            strategy_name=candidate.strategy_name or candidate.strategy_family,
        )
        historical_score = historical_performance_score(
            self.promotion_service,
            strategy_name=candidate.strategy_name or candidate.strategy_family,
        )
        exposure_score, exposure_notes = self._exposure_score(candidate)
        liquidity_score = candidate.liquidity_score
        if order_book is not None:
            liquidity_score = max(liquidity_score, self._liquidity_score_from_order_book(order_book))

        expected_value_score = normalize_expected_value_bps(
            candidate.expected_value_bps,
            ceiling=max(self.settings.strategy_owner_expected_value_ceiling_bps, 1.0),
        )
        overall_score = clamp(
            (candidate.confidence * self.settings.strategy_owner_weight_confidence)
            + (expected_value_score * self.settings.strategy_owner_weight_expected_value)
            + (liquidity_score * self.settings.strategy_owner_weight_liquidity)
            + (candidate.freshness_score * self.settings.strategy_owner_weight_freshness)
            + (execution_score * self.settings.strategy_owner_weight_execution_quality)
            + (provider_score * self.settings.strategy_owner_weight_provider_health)
            + (regime_score * self.settings.strategy_owner_weight_regime)
            + (exposure_score * self.settings.strategy_owner_weight_exposure)
            + (historical_score * self.settings.strategy_owner_weight_historical_performance)
        )
        notes = list(candidate.notes)
        notes.extend(provider_notes)
        notes.extend(regime_notes)
        notes.extend(exposure_notes)
        return replace(
            candidate,
            liquidity_score=round(liquidity_score, 6),
            execution_quality_score=round(execution_score, 6),
            provider_health_score=round(provider_score, 6),
            regime_score=round(regime_score, 6),
            exposure_score=round(exposure_score, 6),
            historical_performance_score=round(historical_score, 6),
            overall_score=round(overall_score, 6),
            notes=notes,
        )

    def rejection_reasons(self, candidate: StrategyDecisionCandidate) -> list[str]:
        reasons: list[str] = []
        expected_value_floor = (
            self.settings.min_net_edge_after_costs_bps
            if candidate.metadata.get("cost_aware")
            else self.settings.strategy_owner_min_expected_value_bps
        )
        if candidate.expected_value_bps < expected_value_floor:
            reasons.append(
                "net_edge_after_costs_below_minimum"
                if candidate.metadata.get("cost_aware")
                else "expected_value_below_floor"
            )
        if candidate.confidence < self.settings.strategy_owner_min_confidence:
            reasons.append("confidence_below_floor")
        if candidate.liquidity_score < self.settings.strategy_owner_min_liquidity_score:
            reasons.append("liquidity_below_floor")
        if candidate.freshness_score < self.settings.strategy_owner_min_freshness_score:
            reasons.append("stale_candidate")
        if candidate.execution_quality_score < self.settings.strategy_owner_min_execution_quality_score:
            reasons.append("execution_quality_degraded")
        if candidate.provider_health_score < self.settings.strategy_owner_min_provider_health_score:
            reasons.append("provider_health_degraded")
        if candidate.regime_score < self.settings.strategy_owner_min_regime_score:
            reasons.append("regime_mismatch")
        if candidate.exposure_score < self.settings.strategy_owner_min_exposure_score:
            reasons.append("exposure_constrained")
        if candidate.historical_performance_score < self.settings.strategy_owner_min_historical_performance_score:
            reasons.append("historical_performance_weak")
        if candidate.overall_score < self.settings.strategy_owner_min_overall_score:
            reasons.append("overall_score_below_floor")
        allowed, gate_reasons = gate_strategy(
            self.promotion_service,
            strategy_name=candidate.strategy_name or candidate.strategy_family,
        )
        if not allowed:
            reasons.extend(gate_reasons)
        # RiskService reevaluates dynamic locks before every executable decision,
        # allowing recovered market conditions to clear a lock without bypassing it.
        return reasons

    def _provider_health_score(self, provider_names: list[str]) -> tuple[float, list[str]]:
        if self.provider_health_service is None or not provider_names:
            return 0.65, []
        snapshots: list[ProviderHealthSnapshot] = []
        for name in provider_names:
            snapshot = self.provider_health_service.get_provider(name)
            if snapshot is not None:
                snapshots.append(snapshot)
        if not snapshots:
            return 0.65, []
        mapping = {"healthy": 1.0, "degraded": 0.5, "unhealthy": 0.0}
        score = sum(mapping.get(item.status, 0.4) for item in snapshots) / len(snapshots)
        notes = [f"provider_status:{item.provider_name}={item.status}" for item in snapshots]
        return clamp(score), notes

    def _regime_score(self, symbol_or_market: str, direction: str) -> tuple[float, list[str]]:
        if self.regime_service is None or symbol_or_market.upper() not in self.settings.signals_supported_symbols:
            return 0.6, []
        regime: RegimeSnapshot | None = self.regime_service.get_current(symbol_or_market.upper())
        if regime is None:
            return 0.6, []
        notes = [f"regime={regime.regime}"]
        if regime.regime == "risk_off":
            return 0.2, notes
        if direction == "long" and regime.regime == "trending_up":
            return 1.0, notes
        if direction == "short" and regime.regime == "trending_down":
            return 1.0, notes
        if regime.regime in {"volatile_chop", "compressed_breakout_setup"}:
            return 0.55, notes
        return 0.45, notes

    def _exposure_score(self, candidate: StrategyDecisionCandidate) -> tuple[float, list[str]]:
        if self.risk_service is None:
            return 0.7, []
        summary = self.risk_service.get_summary()
        notes = [f"open_positions={summary.open_positions}", f"open_risk_pct={summary.open_risk_pct}"]
        if summary.global_risk_lock:
            return 0.0, notes + ["global_risk_lock=true"]
        remaining_slots = max(self.settings.max_concurrent_positions - summary.open_positions, 0)
        slot_score = remaining_slots / max(self.settings.max_concurrent_positions, 1)
        risk_headroom = max(0.0, 1.0 - (summary.open_risk_pct / max(self.settings.max_open_risk_pct, 1e-9)))
        return clamp((slot_score * 0.45) + (risk_headroom * 0.55)), notes

    def _liquidity_score_from_order_book(self, order_book: OrderBookSnapshot) -> float:
        if not order_book.bids or not order_book.asks:
            return 0.0
        top_bid = order_book.bids[0]
        top_ask = order_book.asks[0]
        if top_bid.price <= 0 or top_ask.price <= 0:
            return 0.0
        midpoint = (top_bid.price + top_ask.price) / 2
        gross_depth = sum(level.quantity for level in order_book.bids[:5] + order_book.asks[:5]) * midpoint
        if gross_depth <= 0:
            return 0.0
        return clamp(gross_depth / max(self.settings.strategy_owner_liquidity_depth_target_usd, 1.0))

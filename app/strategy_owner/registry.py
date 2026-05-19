from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

from app.alpha_fusion.types import AlphaSourceReading, FusedAlphaSignal
from app.arbitrage.types import BasisFundingOpportunity
from app.event_signals.types import EventSignalCandidate
from app.features.microstructure.types import MicrostructureFeatureSnapshot
from app.market_data.types import OrderBookSnapshot, TickerSnapshot
from app.polymarket.types import PolymarketOpportunity
from app.signals.types import CandidateSignal
from app.strategies.latency_arbitrage.types import LatencyArbOpportunity
from app.strategies.market_making.types import MarketMakingQuote
from app.strategy_owner.types import StrategyDecisionCandidate
from app.wallet_intel.types import WalletSignal


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _age_score(timestamp: datetime, *, max_age_seconds: int) -> float:
    age_seconds = max((utc_now() - timestamp).total_seconds(), 0.0)
    if max_age_seconds <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (age_seconds / max_age_seconds)))


class StrategyOwnerRegistry:
    def __init__(self, *, settings: object) -> None:
        self.settings = settings

    def from_signal(self, item: CandidateSignal, *, ticker: TickerSnapshot | None, order_book: OrderBookSnapshot | None) -> StrategyDecisionCandidate:
        liquidity_score = self._crypto_liquidity_score(ticker, order_book)
        expected_value_bps = max(item.reward_risk_ratio, 0.0) * max(item.confidence_score / 100.0, 0.0) * 100.0
        return StrategyDecisionCandidate(
            candidate_id=item.signal_id,
            source_name="signal_service",
            strategy_family=item.strategy_name,
            symbol_or_market=item.symbol,
            direction=item.side,
            confidence=max(min(item.confidence_score / 100.0, 1.0), 0.0),
            expected_value_bps=round(expected_value_bps, 6),
            liquidity_score=liquidity_score,
            freshness_score=_age_score(item.generated_at, max_age_seconds=self.settings.strategy_owner_max_candidate_age_seconds),
            execution_quality_score=0.55,
            provider_health_score=0.65,
            regime_score=0.6,
            exposure_score=0.7,
            historical_performance_score=0.55,
            overall_score=0.0,
            timestamp=item.generated_at,
            expected_holding_period="intra-day",
            tradable=True,
            requires_risk_review=True,
            source_reference_id=item.signal_id,
            strategy_name=item.strategy_name,
            entry_price=item.entry_price,
            stop_loss=item.stop_loss,
            target_1=item.target_1,
            target_2=item.target_2,
            reward_risk_ratio=item.reward_risk_ratio,
            notes=list(item.rationale),
            metadata={"indicators_snapshot": item.indicators_snapshot},
        )

    def from_fused_signal(self, item: FusedAlphaSignal, *, ticker: TickerSnapshot | None, order_book: OrderBookSnapshot | None) -> StrategyDecisionCandidate:
        liquidity_score = self._crypto_liquidity_score(ticker, order_book)
        return StrategyDecisionCandidate(
            candidate_id=f"sod_{item.signal_id}",
            source_name="alpha_fusion",
            strategy_family=item.strategy_family,
            symbol_or_market=item.symbol,
            direction=item.direction,
            confidence=item.confidence,
            expected_value_bps=round(item.score * 100.0, 6),
            liquidity_score=liquidity_score,
            freshness_score=_age_score(item.generated_at, max_age_seconds=self.settings.strategy_owner_max_candidate_age_seconds),
            execution_quality_score=0.55,
            provider_health_score=0.65,
            regime_score=0.6,
            exposure_score=0.7,
            historical_performance_score=0.55,
            overall_score=0.0,
            timestamp=item.generated_at,
            expected_holding_period=item.expected_holding_period,
            tradable=item.tradable,
            requires_risk_review=False,
            source_reference_id=item.signal_id,
            strategy_name=item.strategy_family,
            notes=list(item.explanation),
            metadata={"source_breakdown": item.source_breakdown, "veto_factors": item.veto_factors},
        )

    def from_basis_opportunity(self, item: BasisFundingOpportunity) -> StrategyDecisionCandidate:
        return StrategyDecisionCandidate(
            candidate_id=f"sod_{item.opportunity_id}",
            source_name="basis_funding",
            strategy_family="basis_funding",
            symbol_or_market=item.symbol,
            direction=item.recommended_direction,
            confidence=item.confidence,
            expected_value_bps=item.net_edge_estimate,
            liquidity_score=1.0 if item.tradable else 0.25,
            freshness_score=_age_score(item.timestamp, max_age_seconds=self.settings.strategy_owner_max_candidate_age_seconds),
            execution_quality_score=0.55,
            provider_health_score=0.65,
            regime_score=0.55,
            exposure_score=0.7,
            historical_performance_score=0.55,
            overall_score=0.0,
            timestamp=item.timestamp,
            expected_holding_period=item.expected_holding_period,
            tradable=item.tradable,
            requires_risk_review=False,
            source_reference_id=item.opportunity_id,
            strategy_name="basis_funding",
            notes=list(item.explanation),
            metadata={"opportunity_type": item.opportunity_type, "basis_value": item.basis_value, "funding_value": item.funding_value},
        )

    def from_microstructure(self, item: MicrostructureFeatureSnapshot) -> StrategyDecisionCandidate:
        return StrategyDecisionCandidate(
            candidate_id=f"sod_{item.snapshot_id}",
            source_name="binance_microstructure",
            strategy_family="microstructure",
            symbol_or_market=item.symbol,
            direction=item.direction,
            confidence=item.confidence,
            expected_value_bps=round(max(item.confidence, 0.0) * 20.0, 6),
            liquidity_score=max(min((item.total_depth_usd or 0.0) / max(self.settings.strategy_owner_liquidity_depth_target_usd, 1.0), 1.0), 0.0),
            freshness_score=_age_score(item.timestamp, max_age_seconds=self.settings.strategy_owner_max_candidate_age_seconds),
            execution_quality_score=0.55,
            provider_health_score=0.65,
            regime_score=0.55,
            exposure_score=0.7,
            historical_performance_score=0.55,
            overall_score=0.0,
            timestamp=item.timestamp,
            expected_holding_period="seconds_to_minutes",
            tradable=item.signal_policy not in {"no_trade", "unsafe_to_trade"},
            requires_risk_review=False,
            source_reference_id=item.snapshot_id,
            strategy_name="microstructure",
            notes=list(item.explanation),
            metadata={
                "signal_policy": item.signal_policy,
                "market_state": item.market_state,
                "spread_state": item.spread_state,
            },
        )

    def from_polymarket(self, item: PolymarketOpportunity) -> StrategyDecisionCandidate:
        return StrategyDecisionCandidate(
            candidate_id=f"sod_{item.opportunity_id}",
            source_name="polymarket",
            strategy_family="polymarket_mispricing",
            symbol_or_market=item.market_id,
            direction=item.recommended_direction,
            confidence=item.confidence,
            expected_value_bps=item.net_edge_estimate,
            liquidity_score=max(min((item.liquidity_estimate or 0.0) / max(self.settings.polymarket_min_depth_usd, 1.0), 1.0), 0.0),
            freshness_score=_age_score(item.timestamp, max_age_seconds=self.settings.polymarket_max_data_age_seconds),
            execution_quality_score=0.55,
            provider_health_score=0.65,
            regime_score=0.55,
            exposure_score=0.7,
            historical_performance_score=0.55,
            overall_score=0.0,
            timestamp=item.timestamp,
            expected_holding_period=item.expected_holding_period,
            tradable=item.tradable,
            requires_risk_review=False,
            source_reference_id=item.opportunity_id,
            strategy_name="polymarket_mispricing",
            notes=list(item.explanation),
            metadata={"market_title": item.market_title, "opportunity_type": item.opportunity_type},
        )

    def from_wallet_signal(self, item: WalletSignal) -> StrategyDecisionCandidate:
        tradable = item.recommended_action in {"follow", "fade"} and not bool(item.metadata.get("independent_confirmation_required"))
        return StrategyDecisionCandidate(
            candidate_id=f"sod_{item.signal_id}",
            source_name="wallet_intelligence",
            strategy_family="wallet_intelligence",
            symbol_or_market=item.symbol_or_market,
            direction=item.direction,
            confidence=item.confidence,
            expected_value_bps=round(item.quality_score_snapshot * 20.0, 6),
            liquidity_score=max(0.0, 1.0 - item.crowding_risk),
            freshness_score=_age_score(item.timestamp, max_age_seconds=self.settings.wallet_max_data_age_seconds),
            execution_quality_score=0.55,
            provider_health_score=0.65,
            regime_score=0.5,
            exposure_score=0.7,
            historical_performance_score=item.quality_score_snapshot,
            overall_score=0.0,
            timestamp=item.timestamp,
            expected_holding_period="hours_to_days",
            tradable=tradable,
            requires_risk_review=False,
            source_reference_id=item.signal_id,
            strategy_name="wallet_intelligence",
            notes=list(item.rationale),
            metadata={"wallet_id": item.wallet_id, "recommended_action": item.recommended_action},
        )

    def from_event_signal(self, item: EventSignalCandidate) -> StrategyDecisionCandidate:
        return StrategyDecisionCandidate(
            candidate_id=f"sod_{item.signal_id}",
            source_name="event_signals",
            strategy_family="event_signals",
            symbol_or_market=item.symbol_or_market,
            direction=item.direction,
            confidence=item.confidence,
            expected_value_bps=round(item.importance * item.timeliness_decay * 25.0, 6),
            liquidity_score=0.6,
            freshness_score=item.timeliness_decay,
            execution_quality_score=0.55,
            provider_health_score=0.65,
            regime_score=0.5,
            exposure_score=0.7,
            historical_performance_score=0.55,
            overall_score=0.0,
            timestamp=item.timestamp,
            expected_holding_period=item.expected_holding_period,
            tradable=item.direction != "neutral" and not bool(item.metadata.get("advisory_only")),
            requires_risk_review=False,
            source_reference_id=item.signal_id,
            strategy_name="event_signals",
            notes=list(item.explanation),
            metadata={"event_id": item.event_id, "raw_signal": item.raw_signal},
        )

    def from_latency_arb(self, item: LatencyArbOpportunity) -> StrategyDecisionCandidate:
        return StrategyDecisionCandidate(
            candidate_id=f"sod_{item.opportunity_id}",
            source_name="latency_arbitrage",
            strategy_family="latency_arbitrage",
            symbol_or_market=item.market_id,
            direction=item.recommended_direction,
            confidence=item.confidence,
            expected_value_bps=item.net_edge_bps,
            liquidity_score=max(min(item.depth_usd / max(self.settings.latency_arb_min_depth_usd, 1.0), 1.0), 0.0),
            freshness_score=_age_score(item.timestamp, max_age_seconds=self.settings.latency_arb_max_data_age_sec),
            execution_quality_score=0.5,
            provider_health_score=0.65,
            regime_score=0.55,
            exposure_score=0.6,
            historical_performance_score=0.5,
            overall_score=0.0,
            timestamp=item.timestamp,
            expected_holding_period="minutes",
            tradable=item.tradable,
            requires_risk_review=False,
            source_reference_id=item.opportunity_id,
            strategy_name="latency_arbitrage",
            notes=list(item.explanation),
            metadata=item.metadata,
        )

    def from_market_making(self, item: MarketMakingQuote) -> StrategyDecisionCandidate:
        return StrategyDecisionCandidate(
            candidate_id=f"sod_{item.quote_id}",
            source_name="market_making_research",
            strategy_family="market_making_research",
            symbol_or_market=item.market_id,
            direction="neutral",
            confidence=min(1.0, item.expected_spread_capture_bps / max(self.settings.market_making_min_spread_bps, 1.0)),
            expected_value_bps=item.expected_spread_capture_bps,
            liquidity_score=0.65,
            freshness_score=_age_score(item.timestamp, max_age_seconds=self.settings.strategy_owner_max_candidate_age_seconds),
            execution_quality_score=0.45,
            provider_health_score=0.65,
            regime_score=0.5,
            exposure_score=0.65,
            historical_performance_score=0.45,
            overall_score=0.0,
            timestamp=item.timestamp,
            expected_holding_period="minutes_to_hours",
            tradable=False,
            requires_risk_review=False,
            source_reference_id=item.quote_id,
            strategy_name="market_making_research",
            notes=list(item.explanation),
            metadata={"quoted_bid": item.quoted_bid, "quoted_ask": item.quoted_ask, **item.metadata},
        )

    def from_source_reading(self, item: AlphaSourceReading) -> StrategyDecisionCandidate:
        return StrategyDecisionCandidate(
            candidate_id=f"sod_{item.reading_id}",
            source_name=item.source_name,
            strategy_family=item.strategy_family,
            symbol_or_market=item.symbol_or_market,
            direction=item.direction,
            confidence=item.confidence,
            expected_value_bps=round(item.confidence * 10.0, 6),
            liquidity_score=0.55,
            freshness_score=_age_score(item.timestamp, max_age_seconds=self.settings.strategy_owner_max_candidate_age_seconds),
            execution_quality_score=0.55,
            provider_health_score=0.65,
            regime_score=0.55,
            exposure_score=0.7,
            historical_performance_score=0.55,
            overall_score=0.0,
            timestamp=item.timestamp,
            expected_holding_period=item.expected_holding_period,
            tradable=True,
            requires_risk_review=False,
            source_reference_id=item.reading_id,
            strategy_name=item.strategy_family,
            notes=[],
            metadata={"raw_signal": item.raw_signal, **dict(item.metadata)},
        )

    def to_metrics_snapshot(self, candidate: StrategyDecisionCandidate) -> dict[str, float | str | bool | None]:
        return {
            "confidence": round(candidate.confidence, 6),
            "expected_value_bps": round(candidate.expected_value_bps, 6),
            "liquidity_score": round(candidate.liquidity_score, 6),
            "freshness_score": round(candidate.freshness_score, 6),
            "execution_quality_score": round(candidate.execution_quality_score, 6),
            "provider_health_score": round(candidate.provider_health_score, 6),
            "regime_score": round(candidate.regime_score, 6),
            "exposure_score": round(candidate.exposure_score, 6),
            "historical_performance_score": round(candidate.historical_performance_score, 6),
            "overall_score": round(candidate.overall_score, 6),
            "tradable": candidate.tradable,
            "requires_risk_review": candidate.requires_risk_review,
            "strategy_name": candidate.strategy_name,
        }

    def _crypto_liquidity_score(self, ticker: TickerSnapshot | None, order_book: OrderBookSnapshot | None) -> float:
        if ticker is None and order_book is None:
            return 0.55
        spread_penalty = 0.0
        if ticker is not None and ticker.spread_bps is not None:
            spread_penalty = min(max(ticker.spread_bps / 20.0, 0.0), 0.8)
        depth_score = 0.55
        if order_book is not None and order_book.bids and order_book.asks:
            midpoint = (order_book.bids[0].price + order_book.asks[0].price) / 2
            depth_usd = sum(level.quantity for level in order_book.bids[:5] + order_book.asks[:5]) * midpoint
            depth_score = max(min(depth_usd / max(self.settings.strategy_owner_liquidity_depth_target_usd, 1.0), 1.0), 0.0)
        return max(min(depth_score - (spread_penalty * 0.35), 1.0), 0.0)

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone

from app.config.settings import Settings, get_settings
from app.risk.types import RiskValidationInput
from app.signals.schemas import normalize_requested_symbols
from app.signals.types import CandidateSignal
from app.strategy_owner.evaluator import StrategyCandidateEvaluator
from app.strategy_owner.registry import StrategyOwnerRegistry
from app.strategy_owner.types import (
    StrategyDecisionCandidate,
    StrategyOwnerDecision,
    StrategyOwnerEvaluationResult,
    StrategyOwnerSummary,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrategyOwnerService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        signal_service: object | None = None,
        alpha_fusion_service: object | None = None,
        arbitrage_service: object | None = None,
        microstructure_service: object | None = None,
        polymarket_service: object | None = None,
        wallet_intel_service: object | None = None,
        event_signals_service: object | None = None,
        mirofish_adapter: object | None = None,
        latency_arb_service: object | None = None,
        market_making_service: object | None = None,
        market_data_service: object | None = None,
        provider_health_service: object | None = None,
        execution_quality_service: object | None = None,
        regime_service: object | None = None,
        portfolio_brain_service: object | None = None,
        promotion_service: object | None = None,
        risk_service: object | None = None,
        repo: object | None = None,
        events_repo: object | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.signal_service = signal_service
        self.alpha_fusion_service = alpha_fusion_service
        self.arbitrage_service = arbitrage_service
        self.microstructure_service = microstructure_service
        self.polymarket_service = polymarket_service
        self.wallet_intel_service = wallet_intel_service
        self.event_signals_service = event_signals_service
        self.mirofish_adapter = mirofish_adapter
        self.latency_arb_service = latency_arb_service
        self.market_making_service = market_making_service
        self.market_data_service = market_data_service
        self.provider_health_service = provider_health_service
        self.execution_quality_service = execution_quality_service
        self.regime_service = regime_service
        self.portfolio_brain_service = portfolio_brain_service
        self.promotion_service = promotion_service
        self.risk_service = risk_service
        self.repo = repo
        self.events_repo = events_repo
        self.registry = StrategyOwnerRegistry(settings=self.settings)
        self.evaluator = StrategyCandidateEvaluator(
            settings=self.settings,
            provider_health_service=provider_health_service,
            regime_service=regime_service,
            execution_quality_service=execution_quality_service,
            promotion_service=promotion_service,
            risk_service=risk_service,
        )
        self._candidates: list[StrategyDecisionCandidate] = []
        self._decisions: list[StrategyOwnerDecision] = []

    async def evaluate(
        self,
        *,
        symbols: list[str] | None = None,
        markets: list[str] | None = None,
    ) -> StrategyOwnerEvaluationResult:
        normalized_symbols = normalize_requested_symbols(symbols) or [item.upper() for item in self.settings.signals_supported_symbols]
        candidates = await self._collect_candidates(symbols=normalized_symbols, markets=markets or [])
        decisions: list[StrategyOwnerDecision] = []
        accepted_count = 0
        rejected_count = 0
        forwarded_to_risk_count = 0

        for candidate in candidates:
            rejection_reasons = self.evaluator.rejection_reasons(candidate)
            status = "accepted_for_monitoring"
            rejection_reason = None
            forwarded_to_risk = False
            risk_assessment_id = None
            explanation = list(candidate.notes)
            if rejection_reasons:
                status = "rejected"
                rejection_reason = rejection_reasons[0]
                explanation.extend(f"rejection:{reason}" for reason in rejection_reasons)
                rejected_count += 1
            elif candidate.requires_risk_review and self.risk_service is not None:
                assessment = await self.risk_service.validate_signal_payload(self._to_risk_input(candidate))
                forwarded_to_risk = True
                risk_assessment_id = assessment.assessment_id
                if assessment.final_decision == "approved_for_review":
                    status = "accepted_for_risk"
                    accepted_count += 1
                    forwarded_to_risk_count += 1
                    explanation.append(f"risk_decision:{assessment.final_decision}")
                else:
                    status = "rejected_by_risk"
                    rejection_reason = assessment.rejection_reasons[0] if assessment.rejection_reasons else assessment.final_decision
                    rejected_count += 1
                    explanation.append(f"risk_decision:{assessment.final_decision}")
                    explanation.extend(f"risk_rejection:{reason}" for reason in assessment.rejection_reasons)
            else:
                accepted_count += 1

            decision = StrategyOwnerDecision(
                decision_id=self._decision_id(candidate.candidate_id, status, candidate.timestamp),
                candidate_id=candidate.candidate_id,
                source_name=candidate.source_name,
                strategy_family=candidate.strategy_family,
                symbol_or_market=candidate.symbol_or_market,
                direction=candidate.direction,
                status=status,
                overall_score=candidate.overall_score,
                forwarded_to_risk=forwarded_to_risk,
                rejection_reason=rejection_reason,
                risk_assessment_id=risk_assessment_id,
                metrics_snapshot=self.registry.to_metrics_snapshot(candidate),
                explanation=explanation,
                timestamp=utc_now(),
                metadata=dict(candidate.metadata),
            )
            decisions.append(decision)
            self._store_candidate(candidate)
            self._store_decision(decision)

        return StrategyOwnerEvaluationResult(
            candidates=candidates,
            decisions=decisions,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            forwarded_to_risk_count=forwarded_to_risk_count,
        )

    def list_candidates(
        self,
        *,
        strategy_family: str | None = None,
        source_name: str | None = None,
        symbol_or_market: str | None = None,
        limit: int = 100,
    ) -> list[StrategyDecisionCandidate]:
        if self.repo is not None:
            return self.repo.list_candidates(
                strategy_family=strategy_family,
                source_name=source_name,
                symbol_or_market=symbol_or_market,
                limit=limit,
            )
        items = list(self._candidates)
        if strategy_family is not None:
            items = [item for item in items if item.strategy_family == strategy_family]
        if source_name is not None:
            items = [item for item in items if item.source_name == source_name]
        if symbol_or_market is not None:
            items = [item for item in items if item.symbol_or_market == symbol_or_market]
        return items[:limit]

    def list_decisions(
        self,
        *,
        status: str | None = None,
        strategy_family: str | None = None,
        limit: int = 100,
    ) -> list[StrategyOwnerDecision]:
        if self.repo is not None:
            return self.repo.list_decisions(status=status, strategy_family=strategy_family, limit=limit)
        items = list(self._decisions)
        if status is not None:
            items = [item for item in items if item.status == status]
        if strategy_family is not None:
            items = [item for item in items if item.strategy_family == strategy_family]
        return items[:limit]

    def list_rejections(self, *, limit: int = 100) -> list[StrategyOwnerDecision]:
        return [
            item
            for item in self.list_decisions(limit=limit)
            if item.status in {"rejected", "rejected_by_risk"}
        ][:limit]

    def build_summary(self) -> StrategyOwnerSummary:
        decisions = self.list_decisions(limit=self.settings.strategy_owner_store_limit)
        candidates = self.list_candidates(limit=self.settings.strategy_owner_store_limit)
        rejection_counter = Counter(item.rejection_reason for item in decisions if item.rejection_reason)
        return StrategyOwnerSummary(
            candidate_count=len(candidates),
            decision_count=len(decisions),
            accepted_count=len([item for item in decisions if item.status in {"accepted_for_monitoring", "accepted_for_risk"}]),
            rejected_count=len([item for item in decisions if item.status in {"rejected", "rejected_by_risk"}]),
            forwarded_to_risk_count=len([item for item in decisions if item.forwarded_to_risk]),
            active_strategy_families=sorted({item.strategy_family for item in candidates}),
            top_rejection_reasons=[reason for reason, _ in rejection_counter.most_common(5)],
            generated_at=utc_now(),
        )

    async def _collect_candidates(
        self,
        *,
        symbols: list[str],
        markets: list[str],
    ) -> list[StrategyDecisionCandidate]:
        items: list[StrategyDecisionCandidate] = []
        ticker_cache: dict[str, object | None] = {}
        order_book_cache: dict[str, object | None] = {}

        async def ticker(symbol: str):
            normalized = symbol.upper()
            if normalized not in ticker_cache:
                ticker_cache[normalized] = await self.market_data_service.get_snapshot(normalized) if self.market_data_service is not None and hasattr(self.market_data_service, "get_snapshot") else None
            return ticker_cache[normalized]

        async def order_book(symbol: str):
            normalized = symbol.upper()
            if normalized not in order_book_cache:
                order_book_cache[normalized] = await self.market_data_service.get_order_book(normalized) if self.market_data_service is not None and hasattr(self.market_data_service, "get_order_book") else None
            return order_book_cache[normalized]

        if self.signal_service is not None and hasattr(self.signal_service, "evaluate_symbols"):
            for signal in await self.signal_service.evaluate_symbols(symbols):
                symbol_ticker = await ticker(signal.symbol)
                symbol_book = await order_book(signal.symbol)
                candidate = self.registry.from_signal(signal, ticker=symbol_ticker, order_book=symbol_book)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["binance_spot_market_data", "binance_futures_market_data"], order_book=symbol_book))

        if self.alpha_fusion_service is not None and hasattr(self.alpha_fusion_service, "evaluate_targets"):
            targets = list(symbols) + list(markets)
            for fused in await self.alpha_fusion_service.evaluate_targets(targets):
                symbol_ticker = await ticker(fused.symbol) if fused.symbol.upper() in symbols else None
                symbol_book = await order_book(fused.symbol) if fused.symbol.upper() in symbols else None
                candidate = self.registry.from_fused_signal(fused, ticker=symbol_ticker, order_book=symbol_book)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["binance_spot_market_data"], order_book=symbol_book))

        if self.arbitrage_service is not None and hasattr(self.arbitrage_service, "evaluate_symbols"):
            for opportunity in await self.arbitrage_service.evaluate_symbols(symbols):
                symbol_book = await order_book(opportunity.symbol)
                candidate = self.registry.from_basis_opportunity(opportunity)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["binance_futures_market_data"], order_book=symbol_book))

        if self.microstructure_service is not None and hasattr(self.microstructure_service, "compute_batch"):
            for snapshot in await self.microstructure_service.compute_batch(symbols):
                symbol_book = await order_book(snapshot.symbol)
                candidate = self.registry.from_microstructure(snapshot)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["binance_spot_market_data"], order_book=symbol_book))

        if self.polymarket_service is not None and hasattr(self.polymarket_service, "evaluate_opportunities"):
            opportunities = await self.polymarket_service.evaluate_opportunities()
            for opportunity in opportunities:
                if markets and opportunity.market_id not in set(markets):
                    continue
                candidate = self.registry.from_polymarket(opportunity)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["polymarket"]))

        if self.wallet_intel_service is not None and hasattr(self.wallet_intel_service, "list_signals"):
            for signal in self.wallet_intel_service.list_signals(limit=100):
                candidate = self.registry.from_wallet_signal(signal)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["wallet_intel"]))

        if self.event_signals_service is not None and hasattr(self.event_signals_service, "list_signals"):
            for signal in self.event_signals_service.list_signals(limit=100):
                candidate = self.registry.from_event_signal(signal)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["event_signals"]))

        if self.mirofish_adapter is not None and hasattr(self.mirofish_adapter, "latest"):
            latest = self.mirofish_adapter.latest()
            if latest is not None and hasattr(latest, "source_name"):
                reading = self._mirofish_to_source_reading(latest)
                candidate = self.registry.from_source_reading(reading)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["mirofish"]))

        if self.latency_arb_service is not None and hasattr(self.latency_arb_service, "evaluate"):
            for opportunity in await self.latency_arb_service.evaluate():
                candidate = self.registry.from_latency_arb(opportunity)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["polymarket", "binance_spot_market_data"]))

        if self.market_making_service is not None and hasattr(self.market_making_service, "evaluate_quotes"):
            for quote in await self.market_making_service.evaluate_quotes():
                candidate = self.registry.from_market_making(quote)
                items.append(self.evaluator.enrich_candidate(candidate, provider_names=["polymarket"]))

        items.sort(key=lambda item: (item.overall_score, item.confidence, item.expected_value_bps), reverse=True)
        return items[: self.settings.strategy_owner_store_limit]

    def _store_candidate(self, candidate: StrategyDecisionCandidate) -> None:
        self._candidates.insert(0, candidate)
        self._candidates = self._candidates[: self.settings.strategy_owner_store_limit]
        if self.repo is not None:
            self.repo.upsert_candidate(candidate)

    def _store_decision(self, decision: StrategyOwnerDecision) -> None:
        self._decisions.insert(0, decision)
        self._decisions = self._decisions[: self.settings.strategy_owner_store_limit]
        if self.repo is not None:
            self.repo.append_decision(decision)
        if self.events_repo is not None and hasattr(self.events_repo, "append_event"):
            self.events_repo.append_event(
                event_type="strategy_owner_decision",
                entity_id=decision.decision_id,
                symbol=decision.symbol_or_market if decision.symbol_or_market.upper() in self.settings.signals_supported_symbols else None,
                payload={"status": decision.status, "strategy_family": decision.strategy_family, "candidate_id": decision.candidate_id},
            )

    def _to_risk_input(self, candidate: StrategyDecisionCandidate) -> RiskValidationInput:
        return RiskValidationInput(
            signal_id=candidate.candidate_id,
            symbol=candidate.symbol_or_market.upper(),
            side=candidate.direction,
            strategy_name=candidate.strategy_name or candidate.strategy_family,
            confidence_score=int(round(candidate.confidence * 100.0)),
            entry_price=float(candidate.entry_price or 0.0),
            stop_loss=float(candidate.stop_loss or 0.0),
            target_1=float(candidate.target_1 or 0.0),
            target_2=float(candidate.target_2) if candidate.target_2 is not None else None,
            reward_risk_ratio=candidate.reward_risk_ratio,
            rationale=list(candidate.notes),
            generated_at=candidate.timestamp,
            metadata={"source_name": candidate.source_name, **dict(candidate.metadata)},
        )

    def _mirofish_to_source_reading(self, latest: object):
        from app.alpha_fusion.types import AlphaSourceReading

        source_name = getattr(latest, "source_name", "mirofish_simulation")
        symbol_or_market = getattr(latest, "symbol_or_market", "UNKNOWN")
        direction = getattr(latest, "direction_bias", "neutral")
        confidence = float(getattr(latest, "scenario_confidence", 0.5))
        timestamp = getattr(latest, "simulation_timestamp", utc_now())
        explanation = getattr(latest, "explanation", "")
        metadata = getattr(latest, "metadata", {})
        return AlphaSourceReading(
            reading_id=f"src_mirofish_{hashlib.sha1(f'{symbol_or_market}|{timestamp.isoformat()}'.encode('utf-8')).hexdigest()[:12]}",
            source_name=source_name,
            symbol_or_market=symbol_or_market,
            direction=direction,
            confidence=confidence,
            expected_holding_period="scenario_window",
            strategy_family="mirofish_simulation",
            raw_signal={"explanation": explanation},
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
            timestamp=timestamp,
        )

    def _decision_id(self, candidate_id: str, status: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{candidate_id}|{status}|{timestamp.astimezone(timezone.utc).isoformat()}".encode("utf-8")).hexdigest()
        return f"sod_{digest[:12]}"

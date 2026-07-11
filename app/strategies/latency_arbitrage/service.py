from __future__ import annotations

import hashlib
from collections import Counter, OrderedDict
from dataclasses import replace
from datetime import datetime, timezone

from app.alpha_fusion.types import AlphaSourceReading
from app.config.settings import Settings, get_settings
from app.market_data.types import PricePoint
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.polymarket.types import PolymarketOrderBook
from app.strategies.latency_arbitrage.crypto_reference_model import (
    build_realtime_reference_state,
)
from app.strategies.latency_arbitrage.edge_calculator import estimate_edge_bps, estimate_fair_probability
from app.strategies.latency_arbitrage.polymarket_mapping import LatencyArbMarketMapping, map_market
from app.strategies.latency_arbitrage.types import LatencyArbOpportunity


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LatencyArbitrageService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        market_data_service: object | None = None,
        polymarket_service: object | None = None,
        provider_health_service: object | None = None,
        source_repo: AlphaSourcesRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.market_data_service = market_data_service
        self.polymarket_service = polymarket_service
        self.provider_health_service = provider_health_service
        self.source_repo = source_repo
        self.events_repo = events_repo
        self._opportunities: OrderedDict[str, LatencyArbOpportunity] = OrderedDict()
        self._rejection_counts: Counter[str] = Counter()

    async def evaluate(self) -> list[LatencyArbOpportunity]:
        self._rejection_counts.clear()
        if not self.settings.latency_arb_enabled:
            return []
        if self.polymarket_service is None or self.market_data_service is None:
            self._reject("required_service_unavailable")
            return []
        if not await self._providers_usable():
            return []

        markets = await self.polymarket_service.list_markets()
        opportunities: list[LatencyArbOpportunity] = []
        eligible_symbols = set(self.settings.latency_arb_symbols)
        evaluated_markets = 0
        for market in markets:
            mapping = map_market(market)
            if mapping is None or mapping.symbol not in eligible_symbols:
                continue
            if evaluated_markets >= self.settings.latency_arb_max_markets:
                break
            evaluated_markets += 1
            if mapping.duration_minutes not in set(self.settings.latency_arb_allowed_durations_minutes):
                self._reject("unsupported_or_unknown_market_duration")
                continue
            if market.status != "open":
                self._reject("market_not_open")
                continue

            order_book = await self._get_polymarket_orderbook(mapping.market_id)
            if order_book is None:
                self._reject("order_book_unavailable")
                continue
            if self._is_stale(order_book.captured_at):
                self._reject("polymarket_book_stale")
                continue
            if self.settings.latency_arb_require_streaming_book and order_book.source != "clob_websocket":
                self._reject("streaming_order_book_required")
                continue
            if order_book.depth_usd < self.settings.latency_arb_min_depth_usd:
                self._reject("insufficient_depth")
                continue
            if order_book.spread_bps is not None and order_book.spread_bps > self.settings.latency_arb_max_spread_bps:
                self._reject("spread_too_wide")
                continue
            if mapping.close_time is None:
                self._reject("expiry_unavailable")
                continue
            seconds_to_expiry = max((mapping.close_time - utc_now()).total_seconds(), 0.0)
            if seconds_to_expiry <= self.settings.latency_arb_min_time_to_expiry_sec:
                self._reject("time_to_expiry_too_low")
                continue

            snapshot = await self._call_market_data("get_snapshot", mapping.symbol)
            candles = await self._call_market_data(
                "get_candles",
                mapping.symbol,
                self.settings.signals_trigger_timeframe,
            )
            candles = list(candles or [])
            price_history = await self._price_history(mapping.symbol)
            state = build_realtime_reference_state(
                mapping.symbol,
                snapshot=snapshot,
                price_history=price_history,
                candles_5m=candles,
                now=utc_now(),
                max_age_seconds=self.settings.latency_arb_max_data_age_sec,
            )
            if state is None:
                self._reject("binance_reference_stale_or_unavailable")
                continue
            if (
                self.settings.latency_arb_require_realtime_reference
                and state.reference_fidelity != "realtime_price_history"
            ):
                self._reject("realtime_reference_history_required")
                continue

            mapping = self._mapping_with_inferred_threshold(mapping, price_history)
            if mapping.threshold is None:
                self._reject("reference_threshold_unavailable")
                continue
            fair_yes_probability, probability_meta = estimate_fair_probability(
                mapping,
                state,
                seconds_to_expiry=seconds_to_expiry,
            )
            yes_mid = _midpoint(order_book.yes_bid, order_book.yes_ask)
            no_mid = _midpoint(order_book.no_bid, order_book.no_ask)
            if yes_mid is None or no_mid is None:
                self._reject("two_sided_prices_unavailable")
                continue
            buy_yes = fair_yes_probability >= yes_mid
            outcome_name = "YES" if buy_yes else "NO"
            fair_probability = fair_yes_probability if buy_yes else 1.0 - fair_yes_probability
            market_probability = yes_mid if buy_yes else no_mid
            asks = order_book.yes_asks if buy_yes else order_book.no_asks
            execution_price = order_book.yes_ask if buy_yes else order_book.no_ask
            if execution_price is None:
                self._reject("executable_ask_unavailable")
                continue

            edge = estimate_edge_bps(
                fair_probability=fair_probability,
                market_probability=market_probability,
                execution_price=execution_price,
                book_asks=asks,
                depth_usd=order_book.depth_usd,
                spread_bps=order_book.spread_bps,
                order_notional_usd=self.settings.latency_arb_paper_order_notional_usd,
                fee_rate=market.fee_rate,
                execution_buffer_bps=self.settings.latency_arb_execution_buffer_bps,
            )
            rejection_reasons: list[str] = []
            if edge["fill_ratio"] < 0.999:
                rejection_reasons.append("paper_order_not_fully_fillable")
            if edge["net_edge_bps"] < self.settings.latency_arb_min_net_edge_bps:
                rejection_reasons.append("net_edge_below_threshold")
            if market.source == "mock":
                rejection_reasons.append("mock_source_not_eligible")
            for reason in rejection_reasons:
                self._reject(reason)
            tradable = not rejection_reasons
            execution_symbol = None
            if hasattr(self.polymarket_service, "register_execution_target"):
                execution_symbol = self.polymarket_service.register_execution_target(
                    mapping.market_id,
                    outcome_name,
                )
            confidence = min(
                1.0,
                abs(fair_probability - market_probability) * 2.5
                + probability_meta["effective_confidence"] * 0.35
                + mapping.mapping_confidence * 0.2,
            )
            opportunity = LatencyArbOpportunity(
                opportunity_id=self._build_id(mapping.market_id, order_book.captured_at),
                market_id=mapping.market_id,
                market_title=mapping.market_title,
                symbol=mapping.symbol,
                timestamp=order_book.captured_at,
                fair_probability=round(fair_probability, 6),
                market_probability=round(market_probability, 6),
                gross_edge_bps=edge["gross_edge_bps"],
                fee_estimate_bps=edge["fee_estimate_bps"],
                slippage_estimate_bps=edge["slippage_estimate_bps"],
                net_edge_bps=edge["net_edge_bps"],
                confidence=round(confidence, 6),
                depth_usd=round(order_book.depth_usd, 6),
                spread_bps=order_book.spread_bps,
                time_to_expiry_seconds=round(seconds_to_expiry, 6),
                tradable=tradable,
                recommended_direction="long" if tradable else "monitor",
                outcome_name=outcome_name,
                execution_price=edge["simulated_fill_price"],
                fill_ratio=edge["fill_ratio"],
                reference_fidelity=state.reference_fidelity,
                book_source=order_book.source,
                rejection_reasons=rejection_reasons,
                paper_only=True,
                explanation=[
                    f"outcome={outcome_name}",
                    f"fair_probability={round(fair_probability, 4)}",
                    f"market_mid={round(market_probability, 4)}",
                    f"simulated_fill={edge['simulated_fill_price']}",
                    f"net_edge_bps={edge['net_edge_bps']}",
                    f"reference_fidelity={state.reference_fidelity}",
                ],
                metadata={
                    "paper_only": True,
                    "market_class": "prediction_market",
                    "market_id": mapping.market_id,
                    "condition_id": market.condition_id,
                    "token_id": market.yes_token_id if buy_yes else market.no_token_id,
                    "execution_symbol": execution_symbol,
                    "outcome": outcome_name,
                    "fee_rate": market.fee_rate,
                    "fees_enabled": market.fees_enabled,
                    "order_notional_usd": self.settings.latency_arb_paper_order_notional_usd,
                    "entry_fee_usd": edge["entry_fee_usd"],
                    "exit_fee_usd": edge["exit_fee_usd"],
                    "fill_ratio": edge["fill_ratio"],
                    "book_source": order_book.source,
                    "mapping": {
                        "direction": mapping.direction,
                        "threshold": mapping.threshold,
                        "duration_minutes": mapping.duration_minutes,
                        "mapping_confidence": mapping.mapping_confidence,
                        "resolution_source": mapping.resolution_source,
                    },
                    "reference_state": {
                        "current_price": state.current_price,
                        "return_30s_pct": state.return_30s_pct,
                        "return_1m_pct": state.return_1m_pct,
                        "return_5m_pct": state.return_5m_pct,
                        "realized_volatility_pct": state.realized_volatility_pct,
                        "reference_fidelity": state.reference_fidelity,
                        "price_point_count": state.price_point_count,
                    },
                    "probability_update": probability_meta,
                    "cost_aware": True,
                },
            )
            self._store(opportunity)
            opportunities.append(opportunity)
        return opportunities

    def list_opportunities(
        self,
        *,
        tradable: bool | None = None,
        limit: int = 100,
    ) -> list[LatencyArbOpportunity]:
        items = list(self._opportunities.values())
        if tradable is not None:
            items = [item for item in items if item.tradable is tradable]
        return items[:limit]

    def build_summary(self) -> dict[str, object]:
        items = self.list_opportunities(limit=50)
        return {
            "count": len(items),
            "tradable_count": len([item for item in items if item.tradable]),
            "symbols": sorted({item.symbol for item in items}),
            "top_net_edge_bps": max((item.net_edge_bps for item in items), default=0.0),
            "rejection_counts": dict(self._rejection_counts),
            "paper_only": True,
        }

    async def as_source_readings(self) -> list[AlphaSourceReading]:
        return [
            AlphaSourceReading(
                reading_id=f"src_{item.opportunity_id}",
                source_name="latency_arbitrage",
                symbol_or_market=item.market_id,
                direction=item.recommended_direction,
                confidence=item.confidence,
                expected_holding_period="minutes",
                strategy_family="latency_arbitrage",
                raw_signal={
                    "net_edge_bps": item.net_edge_bps,
                    "fair_probability": item.fair_probability,
                    "outcome": item.outcome_name,
                    "paper_only": True,
                },
                metadata=item.metadata,
                timestamp=item.timestamp,
            )
            for item in self.list_opportunities(limit=100)
        ]

    async def _providers_usable(self) -> bool:
        if self.provider_health_service is not None and hasattr(self.provider_health_service, "any_unhealthy"):
            if self.provider_health_service.any_unhealthy(["polymarket"]):
                self._reject("polymarket_provider_unhealthy")
                return False
        if hasattr(self.polymarket_service, "get_provider_health"):
            health = await self.polymarket_service.get_provider_health()
            if health.get("status") not in {"healthy", "ok"}:
                self._reject("polymarket_provider_not_healthy")
                return False
            metadata = health.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("source_is_mock"):
                self._reject("mock_provider_not_eligible")
                return False
        return True

    async def _get_polymarket_orderbook(self, market_id: str) -> PolymarketOrderBook | None:
        getter = getattr(self.polymarket_service, "get_orderbook", None)
        if getter is not None:
            return await getter(market_id)
        provider = getattr(self.polymarket_service, "provider", None)
        if provider is None or not hasattr(provider, "get_orderbook"):
            return None
        return await provider.get_orderbook(market_id)

    async def _price_history(self, symbol: str) -> list[PricePoint]:
        getter = getattr(self.market_data_service, "get_price_history", None)
        if getter is None:
            return []
        value = await getter(symbol, seconds=360)
        return list(value or [])

    async def _call_market_data(self, method_name: str, *args: object):
        method = getattr(self.market_data_service, method_name, None)
        if method is None:
            return None
        return await method(*args)

    def _mapping_with_inferred_threshold(
        self,
        mapping: LatencyArbMarketMapping,
        price_history: list[PricePoint],
    ) -> LatencyArbMarketMapping:
        if mapping.threshold is not None or mapping.start_time is None:
            return mapping
        closest = min(
            price_history,
            key=lambda item: abs((item.timestamp - mapping.start_time).total_seconds()),
            default=None,
        )
        if closest is None or abs((closest.timestamp - mapping.start_time).total_seconds()) > 10:
            return mapping
        return replace(mapping, threshold=closest.price, mapping_confidence=max(mapping.mapping_confidence, 0.8))

    def _is_stale(self, timestamp: datetime) -> bool:
        return (utc_now() - timestamp).total_seconds() > self.settings.latency_arb_max_data_age_sec

    def _reject(self, reason: str) -> None:
        self._rejection_counts[reason] += 1

    def _store(self, item: LatencyArbOpportunity) -> None:
        self._opportunities[item.opportunity_id] = item
        self._opportunities.move_to_end(item.opportunity_id, last=False)
        while len(self._opportunities) > 200:
            self._opportunities.popitem(last=True)
        if self.source_repo is not None:
            self.source_repo.upsert_reading(
                AlphaSourceReading(
                    reading_id=f"src_{item.opportunity_id}",
                    source_name="latency_arbitrage",
                    symbol_or_market=item.market_id,
                    direction=item.recommended_direction,
                    confidence=item.confidence,
                    expected_holding_period="minutes",
                    strategy_family="latency_arbitrage",
                    raw_signal={
                        "net_edge_bps": item.net_edge_bps,
                        "tradable": item.tradable,
                        "paper_only": True,
                    },
                    metadata=item.metadata,
                    timestamp=item.timestamp,
                )
            )
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="latency_arb_opportunity_detected",
                entity_id=item.opportunity_id,
                payload={
                    "market_id": item.market_id,
                    "tradable": item.tradable,
                    "paper_only": True,
                    "outcome": item.outcome_name,
                },
            )

    def _build_id(self, market_id: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{market_id}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"larb_{digest[:12]}"


def _midpoint(bid: float | None, ask: float | None) -> float | None:
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    return ask if ask is not None else bid

from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import datetime, timezone

from app.alpha_fusion.types import AlphaSourceReading
from app.config.settings import Settings, get_settings
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.polymarket.types import PolymarketOrderBook
from app.strategies.latency_arbitrage.crypto_reference_model import build_reference_state
from app.strategies.latency_arbitrage.edge_calculator import estimate_edge_bps, estimate_fair_probability
from app.strategies.latency_arbitrage.polymarket_mapping import map_market
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

    async def evaluate(self) -> list[LatencyArbOpportunity]:
        if not self.settings.latency_arb_enabled:
            return []
        if self.provider_health_service is not None and self.provider_health_service.any_unhealthy(["polymarket", "binance_spot_market_data"]):
            return []
        if self.polymarket_service is None or self.market_data_service is None:
            return []
        markets = await self.polymarket_service.list_markets()
        opportunities: list[LatencyArbOpportunity] = []
        eligible_symbols = set(self.settings.latency_arb_symbols)
        for market in markets[: self.settings.latency_arb_max_markets]:
            mapping = map_market(market)
            if mapping is None or mapping.symbol not in eligible_symbols:
                continue
            order_book = await self._get_polymarket_orderbook(mapping.market_id)
            if order_book is None:
                continue
            market_probability = market.yes_price
            if market_probability is None:
                continue
            if self._is_market_stale(market.last_updated_at):
                continue
            if order_book.depth_usd < self.settings.latency_arb_min_depth_usd:
                continue
            if order_book.spread_bps is not None and order_book.spread_bps > self.settings.latency_arb_max_spread_bps:
                continue
            if mapping.close_time is None:
                continue
            seconds_to_expiry = max((mapping.close_time - utc_now()).total_seconds(), 0.0)
            if seconds_to_expiry <= 30:
                continue
            candles = await self.market_data_service.get_candles(mapping.symbol, self.settings.signals_trigger_timeframe)
            if not candles:
                continue
            state = build_reference_state(mapping.symbol, candles)
            if state is None:
                continue
            fair_probability, probability_meta = estimate_fair_probability(mapping, state, seconds_to_expiry=seconds_to_expiry)
            edge = estimate_edge_bps(
                fair_probability=fair_probability,
                market_probability=market_probability,
                depth_usd=order_book.depth_usd,
                spread_bps=order_book.spread_bps,
            )
            tradable = edge["net_edge_bps"] >= self.settings.latency_arb_min_net_edge_bps
            direction = "long" if fair_probability > market_probability else "short"
            opportunity = LatencyArbOpportunity(
                opportunity_id=self._build_id(mapping.market_id, market.last_updated_at),
                market_id=mapping.market_id,
                market_title=mapping.market_title,
                symbol=mapping.symbol,
                timestamp=market.last_updated_at,
                fair_probability=round(fair_probability, 6),
                market_probability=round(market_probability, 6),
                gross_edge_bps=edge["gross_edge_bps"],
                fee_estimate_bps=edge["fee_estimate_bps"],
                slippage_estimate_bps=edge["slippage_estimate_bps"],
                net_edge_bps=edge["net_edge_bps"],
                confidence=min(1.0, abs(fair_probability - market_probability) * 4.0 + probability_meta["effective_confidence"] * 0.4),
                depth_usd=round(order_book.depth_usd, 6),
                spread_bps=order_book.spread_bps,
                time_to_expiry_seconds=round(seconds_to_expiry, 6),
                tradable=tradable,
                recommended_direction=direction if tradable else "monitor",
                explanation=[
                    f"fair_probability={round(fair_probability, 4)}",
                    f"market_probability={round(market_probability, 4)}",
                    f"net_edge_bps={edge['net_edge_bps']}",
                ],
                metadata={
                    "mapping": {
                        "direction": mapping.direction,
                        "threshold": mapping.threshold,
                    },
                    "reference_state": {
                        "current_price": state.current_price,
                        "return_30s_pct": state.return_30s_pct,
                        "return_1m_pct": state.return_1m_pct,
                        "return_5m_pct": state.return_5m_pct,
                        "realized_volatility_pct": state.realized_volatility_pct,
                    },
                    "probability_update": probability_meta,
                },
            )
            self._store(opportunity)
            opportunities.append(opportunity)
        return opportunities

    def list_opportunities(self, *, tradable: bool | None = None, limit: int = 100) -> list[LatencyArbOpportunity]:
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
                raw_signal={"net_edge_bps": item.net_edge_bps, "fair_probability": item.fair_probability},
                metadata=item.metadata,
                timestamp=item.timestamp,
            )
            for item in self.list_opportunities(limit=100)
        ]

    async def _get_polymarket_orderbook(self, market_id: str) -> PolymarketOrderBook | None:
        if self.polymarket_service is None:
            return None
        getter = getattr(self.polymarket_service, "get_orderbook", None)
        if getter is not None:
            return await getter(market_id)
        provider = getattr(self.polymarket_service, "provider", None)
        if provider is None or not hasattr(provider, "get_orderbook"):
            return None
        return await provider.get_orderbook(market_id)

    def _is_market_stale(self, updated_at: datetime) -> bool:
        return (utc_now() - updated_at).total_seconds() > self.settings.latency_arb_max_data_age_sec

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
                    raw_signal={"net_edge_bps": item.net_edge_bps, "tradable": item.tradable},
                    metadata=item.metadata,
                    timestamp=item.timestamp,
                )
            )
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="latency_arb_opportunity_detected",
                entity_id=item.opportunity_id,
                payload={"market_id": item.market_id, "tradable": item.tradable},
            )

    def _build_id(self, market_id: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{market_id}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"larb_{digest[:12]}"

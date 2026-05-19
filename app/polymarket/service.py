from __future__ import annotations

import hashlib
import inspect
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.alpha_fusion.types import AlphaSourceReading
from app.config.settings import Settings, get_settings
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.polymarket_repo import PolymarketRepository
from app.polymarket.providers import (
    MockPolymarketProvider as BaseMockPolymarketProvider,
    RealPolymarketProvider as BaseRealPolymarketProvider,
    build_polymarket_provider,
)
from app.polymarket.types import LinkedMarketValidation, PolymarketMarket, PolymarketOpportunity, PolymarketOrderBook
from app.provider_health.service import ProviderHealthService
from app.provider_health.types import ProviderIngestRun


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PolymarketProvider(Protocol):
    async def list_markets(self) -> list[PolymarketMarket]: ...
    async def get_market(self, market_id: str) -> PolymarketMarket | None: ...
    async def get_orderbook(self, market_id: str) -> PolymarketOrderBook | None: ...
    async def get_recent_trades(self, market_id: str) -> list[dict[str, object]]: ...
    async def get_market_prices(self, market_id: str) -> dict[str, float | None]: ...
    async def get_linked_markets(self, market_id: str | None = None) -> dict[str, list[str]]: ...
    async def health_check(self) -> dict[str, object]: ...


class MockPolymarketProvider(BaseMockPolymarketProvider):
    pass


class RealPolymarketProvider(BaseRealPolymarketProvider):
    pass


class PolymarketService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        provider: PolymarketProvider | None = None,
        repo: PolymarketRepository | None = None,
        source_repo: AlphaSourcesRepository | None = None,
        events_repo: EventsRepository | None = None,
        provider_health_service: ProviderHealthService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or build_polymarket_provider(
            settings=self.settings,
            mock_provider=MockPolymarketProvider(),
        )
        self.repo = repo
        self.source_repo = source_repo
        self.events_repo = events_repo
        self.provider_health_service = provider_health_service
        self._markets: OrderedDict[str, PolymarketMarket] = OrderedDict()
        self._opportunities: OrderedDict[str, PolymarketOpportunity] = OrderedDict()
        self._validations: OrderedDict[str, LinkedMarketValidation] = OrderedDict()

    async def refresh(self) -> None:
        requested_at = utc_now()
        status = "completed"
        notes: list[str] = []
        markets: list[PolymarketMarket] = []
        try:
            markets = await self.provider.list_markets()
            for market in markets:
                self._markets[market.market_id] = market
                if self.repo is not None:
                    self.repo.upsert_market(market)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            raise
        finally:
            if self.provider_health_service is not None:
                await self.provider_health_service.evaluate_provider("polymarket", self.provider)
                self.provider_health_service.record_ingest_run(
                    ProviderIngestRun(
                        run_id=self._build_id("polymarket_refresh", "ingest", requested_at),
                        provider_name="polymarket",
                        dataset_type="markets",
                        requested_at=requested_at,
                        completed_at=utc_now(),
                        status=status,
                        records_requested=len(markets),
                        records_written=len(markets),
                        error_summary="; ".join(notes) if notes else None,
                        notes=notes,
                        metadata={"provider_mode": getattr(self.settings, "polymarket_provider_mode", "mock")},
                    )
                )

    async def list_markets(self) -> list[PolymarketMarket]:
        if not self._markets:
            await self.refresh()
        if self.repo is not None and not self._markets:
            return self.repo.list_markets()
        return list(self._markets.values())

    async def get_market(self, market_id: str) -> PolymarketMarket | None:
        if market_id in self._markets:
            return self._markets[market_id]
        market = await self.provider.get_market(market_id)
        if market is not None:
            self._markets[market.market_id] = market
            if self.repo is not None:
                self.repo.upsert_market(market)
            return market
        if self.repo is not None:
            return self.repo.get_market(market_id)
        return None

    async def evaluate_opportunities(self) -> list[PolymarketOpportunity]:
        markets = await self.list_markets()
        items: list[PolymarketOpportunity] = []
        for market in markets:
            item = await self._build_market_opportunity(market)
            if item is not None:
                items.append(item)
        items.extend(await self._build_linked_market_opportunities(markets))
        return items

    async def get_opportunity(self, opportunity_id: str) -> PolymarketOpportunity | None:
        if opportunity_id in self._opportunities:
            return self._opportunities[opportunity_id]
        if self.repo is not None:
            return self.repo.get_opportunity(opportunity_id)
        return None

    def list_persisted_opportunities(self, *, tradable: bool | None = None, limit: int = 100) -> list[PolymarketOpportunity]:
        items = self.repo.list_opportunities(limit=limit, market="polymarket") if self.repo is not None else list(self._opportunities.values())
        if tradable is not None:
            items = [item for item in items if item.tradable is tradable]
        return items[:limit]

    async def as_source_readings(self) -> list[AlphaSourceReading]:
        opportunities = await self.evaluate_opportunities()
        readings: list[AlphaSourceReading] = []
        for item in opportunities:
            direction = item.recommended_direction
            if direction == "short_yes_long_no":
                direction = "short"
            elif direction == "long_yes_short_no":
                direction = "long"
            readings.append(
                AlphaSourceReading(
                    reading_id=f"src_{item.opportunity_id}",
                    source_name="polymarket_mispricing",
                    symbol_or_market=item.market_id,
                    direction=direction,
                    confidence=item.confidence,
                    expected_holding_period=item.expected_holding_period,
                    strategy_family="polymarket_mispricing",
                    raw_signal={
                        "opportunity_type": item.opportunity_type,
                        "yes_plus_no": item.yes_plus_no,
                        "tradable": item.tradable,
                    },
                    metadata=item.metadata,
                    timestamp=item.timestamp,
                )
            )
        return readings

    async def get_provider_health(self) -> dict[str, object]:
        return await self.provider.health_check()

    async def _build_market_opportunity(self, market: PolymarketMarket) -> PolymarketOpportunity | None:
        orderbook = await self.provider.get_orderbook(market.market_id)
        prices = await self.provider.get_market_prices(market.market_id)
        yes_price = prices.get("yes_price", market.yes_price)
        no_price = prices.get("no_price", market.no_price)
        yes_plus_no = yes_price + no_price if yes_price is not None and no_price is not None else None
        deviation = (yes_plus_no - 1.0) if yes_plus_no is not None else None
        stale_market = (utc_now() - market.last_updated_at).total_seconds() > self.settings.polymarket_max_data_age_seconds
        spread = orderbook.spread_bps if orderbook is not None else None
        depth = orderbook.depth_usd if orderbook is not None else 0.0
        opportunity_type = "cross-market-consistency-monitor"
        direction = "neutral"
        if deviation is not None and abs(deviation) >= 0.03:
            opportunity_type = "yes_no_sum_dislocation"
            direction = "short_yes_long_no" if deviation > 0 else "long_yes_short_no"
        elif spread is not None and spread >= 220:
            opportunity_type = "thin_book_price_gap"
        gross_edge = abs(deviation or 0.0) * 10000 * 0.6 + max((220 - (spread or 220)) / 10, 0.0)
        fee_estimate = 8.0
        slippage_estimate = max(2.0, 9000.0 / max(depth, 1.0))
        net_edge = gross_edge - fee_estimate - slippage_estimate
        confidence = min(1.0, 0.35 + abs(deviation or 0.0) * 4.0 + max(depth / 50000.0, 0.0))
        tradable = (
            not stale_market
            and depth >= self.settings.polymarket_min_depth_usd
            and net_edge >= self.settings.polymarket_min_net_edge_bps
        )
        item = PolymarketOpportunity(
            opportunity_id=self._build_id(market.market_id, opportunity_type, market.last_updated_at),
            market_id=market.market_id,
            market_title=market.title,
            timestamp=market.last_updated_at,
            signal_family="polymarket_mispricing",
            opportunity_type=opportunity_type,
            yes_price=yes_price,
            no_price=no_price,
            yes_plus_no=yes_plus_no,
            deviation_from_one=deviation,
            spread=spread,
            liquidity_estimate=depth,
            stale_market=stale_market,
            gross_edge_estimate=round(gross_edge, 6),
            fee_estimate=round(fee_estimate, 6),
            slippage_estimate=round(slippage_estimate, 6),
            net_edge_estimate=round(net_edge, 6),
            confidence=round(confidence, 6),
            tradable=tradable,
            recommended_direction=direction,
            expected_holding_period="hours_to_days",
            explanation=[
                f"yes+no={round(yes_plus_no, 4) if yes_plus_no is not None else None}",
                f"spread={spread}, depth={depth}",
                f"tradable={tradable}",
            ],
            metadata={"category": market.category, "event_slug": market.event_slug},
        )
        self._store_opportunity(item, orderbook)
        return item

    async def _build_linked_market_opportunities(self, markets: list[PolymarketMarket]) -> list[PolymarketOpportunity]:
        if not self.settings.polymarket_linked_rules_enabled:
            return []
        by_group: dict[str, list[PolymarketMarket]] = {}
        for item in markets:
            if item.linked_group:
                by_group.setdefault(item.linked_group, []).append(item)
        opportunities: list[PolymarketOpportunity] = []
        for group_name, grouped in by_group.items():
            yes_sum = sum(item.yes_price or 0.0 for item in grouped)
            deviation = abs(yes_sum - 1.0) if len(grouped) > 1 else 0.0
            status = "valid" if deviation <= 0.1 else "invalid"
            validation = LinkedMarketValidation(
                validation_id=self._build_id(group_name, "linked", utc_now()),
                rule_name=group_name,
                related_markets=[item.market_id for item in grouped],
                status=status,
                deviation=round(deviation, 6),
                explanation=[f"linked sum deviation={round(deviation, 4)}"],
                detected_at=utc_now(),
                metadata={"market_count": len(grouped)},
            )
            self._validations[validation.validation_id] = validation
            if self.repo is not None:
                self.repo.upsert_linked_validation(validation)
            if status == "invalid":
                anchor = grouped[0]
                item = PolymarketOpportunity(
                    opportunity_id=self._build_id(anchor.market_id, "linked_market_inconsistency", validation.detected_at),
                    market_id=anchor.market_id,
                    market_title=anchor.title,
                    timestamp=validation.detected_at,
                    signal_family="polymarket_mispricing",
                    opportunity_type="linked_market_inconsistency",
                    yes_price=anchor.yes_price,
                    no_price=anchor.no_price,
                    yes_plus_no=yes_sum,
                    deviation_from_one=yes_sum - 1.0,
                    spread=None,
                    liquidity_estimate=None,
                    stale_market=False,
                    gross_edge_estimate=round(deviation * 10000 * 0.5, 6),
                    fee_estimate=6.0,
                    slippage_estimate=3.0,
                    net_edge_estimate=round((deviation * 10000 * 0.5) - 9.0, 6),
                    confidence=round(min(1.0, 0.4 + deviation * 2.5), 6),
                    tradable=(deviation * 10000 * 0.5) - 9.0 >= self.settings.polymarket_min_net_edge_bps,
                    recommended_direction="monitor",
                    expected_holding_period="event_window",
                    explanation=validation.explanation,
                    metadata={"related_markets": validation.related_markets},
                )
                self._store_opportunity(item, None)
                opportunities.append(item)
        return opportunities

    def _store_opportunity(self, opportunity: PolymarketOpportunity, orderbook: PolymarketOrderBook | None) -> None:
        self._opportunities[opportunity.opportunity_id] = opportunity
        self._opportunities.move_to_end(opportunity.opportunity_id, last=False)
        while len(self._opportunities) > 500:
            self._opportunities.popitem(last=True)
        if self.repo is not None:
            self.repo.upsert_opportunity(opportunity)
            if orderbook is not None:
                self.repo.upsert_snapshot(orderbook)
        if self.source_repo is not None:
            self.source_repo.upsert_reading(
                AlphaSourceReading(
                    reading_id=f"src_{opportunity.opportunity_id}",
                    source_name="polymarket_mispricing",
                    symbol_or_market=opportunity.market_id,
                    direction=opportunity.recommended_direction,
                    confidence=opportunity.confidence,
                    expected_holding_period=opportunity.expected_holding_period,
                    strategy_family="polymarket_mispricing",
                    raw_signal={"opportunity_type": opportunity.opportunity_type, "tradable": opportunity.tradable},
                    metadata=opportunity.metadata,
                    timestamp=opportunity.timestamp,
                )
            )
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="polymarket_opportunity_detected",
                entity_id=opportunity.opportunity_id,
                payload={"market_id": opportunity.market_id, "tradable": opportunity.tradable},
            )

    def _build_id(self, entity: str, signal_family: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{entity}|{signal_family}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"pm_{digest[:12]}"

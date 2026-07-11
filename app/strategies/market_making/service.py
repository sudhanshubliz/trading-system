from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import datetime, timezone

from app.alpha_fusion.types import AlphaSourceReading
from app.config.settings import Settings, get_settings
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.probability.bayesian_model import update_probability
from app.probability.types import ProbabilityEvidence
from app.strategies.market_making.types import MarketMakingQuote


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MarketMakingResearchService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        polymarket_service: object | None = None,
        strategy_owner_service: object | None = None,
        source_repo: AlphaSourcesRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.polymarket_service = polymarket_service
        self.strategy_owner_service = strategy_owner_service
        self.source_repo = source_repo
        self.events_repo = events_repo
        self._quotes: OrderedDict[str, MarketMakingQuote] = OrderedDict()

    async def evaluate_quotes(self) -> list[MarketMakingQuote]:
        if not self.settings.market_making_enabled:
            return []
        if self.polymarket_service is None:
            return []
        markets = await self.polymarket_service.list_markets()
        quotes: list[MarketMakingQuote] = []
        owner_candidates = []
        if self.strategy_owner_service is not None and hasattr(self.strategy_owner_service, "list_candidates"):
            owner_candidates = self.strategy_owner_service.list_candidates(limit=200)
        for market in markets[:50]:
            order_book = await self.polymarket_service.get_orderbook(market.market_id)
            if order_book is None or market.yes_price is None:
                continue
            owner_skew = 0.0
            related_candidates = [item for item in owner_candidates if item.symbol_or_market == market.market_id]
            if related_candidates:
                strongest = max(related_candidates, key=lambda item: item.overall_score)
                owner_skew = (strongest.confidence - 0.5) * (1.0 if strongest.direction == "long" else -1.0)
            posterior = update_probability(
                prior=market.yes_price,
                evidence=[
                    ProbabilityEvidence(source_name="polymarket_mid", direction_bias=0.0, confidence=0.4, weight=0.5),
                    ProbabilityEvidence(source_name="strategy_owner", direction_bias=owner_skew, confidence=min(abs(owner_skew) * 1.6, 1.0), weight=1.0),
                ],
            ).posterior
            target_spread_bps = max(self.settings.market_making_min_spread_bps, order_book.spread_bps or self.settings.market_making_min_spread_bps)
            half_spread = target_spread_bps / 20000.0
            quoted_bid = max(0.01, posterior - half_spread)
            quoted_ask = min(0.99, posterior + half_spread)
            adverse_selection_risk_bps = max((order_book.spread_bps or 0.0) * 0.35, 10.0)
            expected_capture = max(target_spread_bps - adverse_selection_risk_bps, 0.0)
            tradable = expected_capture > 0 and order_book.depth_usd >= self.settings.polymarket_min_depth_usd
            quote = MarketMakingQuote(
                quote_id=self._build_id(market.market_id, market.last_updated_at),
                market_id=market.market_id,
                market_title=market.title,
                timestamp=market.last_updated_at,
                fair_probability=round(posterior, 6),
                quoted_bid=round(quoted_bid, 6),
                quoted_ask=round(quoted_ask, 6),
                spread_bps=round((quoted_ask - quoted_bid) * 10000.0, 6),
                max_inventory_usd=self.settings.market_making_max_inventory_usd,
                inventory_bias=round(owner_skew, 6),
                expected_spread_capture_bps=round(expected_capture, 6),
                adverse_selection_risk_bps=round(adverse_selection_risk_bps, 6),
                tradable=tradable,
                recommended_action="quote_both_sides" if tradable else "monitor",
                explanation=[
                    f"fair_probability={round(posterior, 4)}",
                    f"inventory_bias={round(owner_skew, 4)}",
                    f"expected_spread_capture_bps={round(expected_capture, 4)}",
                ],
                metadata={"paper_only": self.settings.market_making_paper_only},
            )
            self._store(quote)
            quotes.append(quote)
        return quotes

    def list_quotes(self, *, tradable: bool | None = None, limit: int = 100) -> list[MarketMakingQuote]:
        items = list(self._quotes.values())
        if tradable is not None:
            items = [item for item in items if item.tradable is tradable]
        return items[:limit]

    async def as_source_readings(self) -> list[AlphaSourceReading]:
        return [
            AlphaSourceReading(
                reading_id=f"src_{item.quote_id}",
                source_name="market_making_research",
                symbol_or_market=item.market_id,
                direction="neutral",
                confidence=min(1.0, item.expected_spread_capture_bps / max(self.settings.market_making_min_spread_bps, 1.0)),
                expected_holding_period="minutes_to_hours",
                strategy_family="market_making_research",
                raw_signal={"quoted_bid": item.quoted_bid, "quoted_ask": item.quoted_ask},
                metadata=item.metadata,
                timestamp=item.timestamp,
            )
            for item in self.list_quotes(limit=100)
        ]

    def _store(self, item: MarketMakingQuote) -> None:
        self._quotes[item.quote_id] = item
        self._quotes.move_to_end(item.quote_id, last=False)
        while len(self._quotes) > 200:
            self._quotes.popitem(last=True)
        if self.source_repo is not None:
            self.source_repo.upsert_reading(
                AlphaSourceReading(
                    reading_id=f"src_{item.quote_id}",
                    source_name="market_making_research",
                    symbol_or_market=item.market_id,
                    direction="neutral",
                    confidence=min(1.0, item.expected_spread_capture_bps / max(self.settings.market_making_min_spread_bps, 1.0)),
                    expected_holding_period="minutes_to_hours",
                    strategy_family="market_making_research",
                    raw_signal={"expected_spread_capture_bps": item.expected_spread_capture_bps},
                    metadata=item.metadata,
                    timestamp=item.timestamp,
                )
            )
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="market_making_quote_generated",
                entity_id=item.quote_id,
                payload={"market_id": item.market_id, "tradable": item.tradable},
            )

    def _build_id(self, market_id: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{market_id}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"mmq_{digest[:12]}"

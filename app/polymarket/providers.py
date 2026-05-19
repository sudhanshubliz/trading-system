from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.config.settings import Settings, get_settings
from app.polymarket.types import PolymarketMarket, PolymarketOrderBook
from app.providers.common import (
    ExistingAsyncClientContext,
    FallbackProviderAdapter,
    ProviderRuntimeState,
    ensure_datetime,
    local_fallback_allowed,
    safe_float,
    utc_now,
)


class MockPolymarketProvider:
    def __init__(self) -> None:
        now = utc_now()
        self._markets = {
            "pm_us_election_yes": PolymarketMarket(
                market_id="pm_us_election_yes",
                title="Will Candidate A win the election?",
                category="politics",
                event_slug="us-election",
                status="open",
                close_time=now,
                last_updated_at=now,
                yes_price=0.58,
                no_price=0.46,
                linked_group="us-election-primary",
                linked_rule="yes_no_sum",
            ),
            "pm_rate_cut_yes": PolymarketMarket(
                market_id="pm_rate_cut_yes",
                title="Will the central bank cut rates this quarter?",
                category="macro",
                event_slug="rate-cut-quarter",
                status="open",
                close_time=now,
                last_updated_at=now,
                yes_price=0.41,
                no_price=0.55,
                linked_group="macro-rate",
                linked_rule="yes_no_sum",
            ),
            "pm_crypto_etf_approval": PolymarketMarket(
                market_id="pm_crypto_etf_approval",
                title="Will a major crypto ETF be approved this month?",
                category="crypto",
                event_slug="crypto-etf-approval",
                status="open",
                close_time=now,
                last_updated_at=now,
                yes_price=0.67,
                no_price=0.29,
                linked_group="crypto-policy",
                linked_rule="bounded_pair_sum",
            ),
            "pm_crypto_etf_delay": PolymarketMarket(
                market_id="pm_crypto_etf_delay",
                title="Will a major crypto ETF approval be delayed this month?",
                category="crypto",
                event_slug="crypto-etf-delay",
                status="open",
                close_time=now,
                last_updated_at=now,
                yes_price=0.44,
                no_price=0.52,
                linked_group="crypto-policy",
                linked_rule="bounded_pair_sum",
            ),
        }

    async def list_markets(self) -> list[PolymarketMarket]:
        return list(self._markets.values())

    async def get_market(self, market_id: str) -> PolymarketMarket | None:
        return self._markets.get(market_id)

    async def get_orderbook(self, market_id: str) -> PolymarketOrderBook | None:
        market = self._markets.get(market_id)
        if market is None:
            return None
        spread_bps = 250.0 if market.market_id == "pm_us_election_yes" else 180.0
        return PolymarketOrderBook(
            market_id=market.market_id,
            yes_bid=max((market.yes_price or 0.5) - 0.02, 0.01),
            yes_ask=min((market.yes_price or 0.5) + 0.02, 0.99),
            no_bid=max((market.no_price or 0.5) - 0.02, 0.01),
            no_ask=min((market.no_price or 0.5) + 0.02, 0.99),
            depth_usd=15000.0 if market.market_id == "pm_us_election_yes" else 7000.0,
            spread_bps=spread_bps,
            captured_at=market.last_updated_at,
        )

    async def get_recent_trades(self, market_id: str) -> list[dict[str, object]]:
        market = self._markets.get(market_id)
        if market is None:
            return []
        return [
            {
                "market_id": market_id,
                "price": market.yes_price,
                "size": 250.0,
                "timestamp": market.last_updated_at.isoformat(),
            }
        ]

    async def get_market_prices(self, market_id: str) -> dict[str, float | None]:
        market = self._markets.get(market_id)
        if market is None:
            return {"yes_price": None, "no_price": None}
        return {"yes_price": market.yes_price, "no_price": market.no_price}

    async def get_linked_markets(self, market_id: str | None = None) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for item in self._markets.values():
            if item.linked_group is None:
                continue
            groups.setdefault(item.linked_group, []).append(item.market_id)
        if market_id is None:
            return groups
        return {key: value for key, value in groups.items() if market_id in value}

    async def health_check(self) -> dict[str, object]:
        return {"status": "healthy", "success_rate": 1.0, "stale_data_flag": False, "error_count": 0}


class RealPolymarketProvider:
    def __init__(self, *, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._runtime = ProviderRuntimeState()

    @property
    def has_successful_fetch(self) -> bool:
        return self._runtime.has_successful_fetch

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.polymarket_base_url.strip())

    async def list_markets(self) -> list[PolymarketMarket]:
        payload = await self._request_json("/v1/markets")
        records = payload if isinstance(payload, list) else payload.get("markets") or payload.get("items") or payload.get("data") or []
        return [self._normalize_market(item) for item in records if isinstance(item, dict) and self._normalize_market(item) is not None]

    async def get_market(self, market_id: str) -> PolymarketMarket | None:
        payload = await self._request_json(f"/v1/markets/{market_id}")
        record = payload.get("market") if isinstance(payload, dict) and isinstance(payload.get("market"), dict) else payload
        if not isinstance(record, dict):
            return None
        return self._normalize_market(record)

    async def get_orderbook(self, market_id: str) -> PolymarketOrderBook | None:
        payload = await self._request_json(f"/v1/markets/{market_id}/book")
        market_data = payload.get("marketData") if isinstance(payload, dict) else None
        record = market_data if isinstance(market_data, dict) else payload
        if not isinstance(record, dict):
            return None
        bids = record.get("bids") or []
        asks = record.get("offers") or record.get("asks") or []
        bid_prices = [self._price_value(item) for item in bids if self._price_value(item) is not None]
        ask_prices = [self._price_value(item) for item in asks if self._price_value(item) is not None]
        yes_bid = max(bid_prices) if bid_prices else None
        yes_ask = min(ask_prices) if ask_prices else None
        no_bid = (1.0 - yes_ask) if yes_ask is not None and 0.0 <= yes_ask <= 1.0 else None
        no_ask = (1.0 - yes_bid) if yes_bid is not None and 0.0 <= yes_bid <= 1.0 else None
        depth_usd = sum((self._price_value(item) or 0.0) * self._quantity_value(item) for item in [*bids[:5], *asks[:5]])
        spread_bps = None
        if yes_bid is not None and yes_ask is not None:
            mid = (yes_bid + yes_ask) / 2
            if mid > 0:
                spread_bps = ((yes_ask - yes_bid) / mid) * 10000
        captured_at = ensure_datetime(record.get("transactTime")) or utc_now()
        slug = str(record.get("marketSlug") or market_id)
        return PolymarketOrderBook(
            market_id=slug,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            depth_usd=round(depth_usd, 6),
            spread_bps=round(spread_bps, 6) if spread_bps is not None else None,
            captured_at=captured_at,
        )

    async def get_recent_trades(self, market_id: str) -> list[dict[str, object]]:
        try:
            payload = await self._request_json(f"/v1/markets/{market_id}/trades")
        except Exception:
            return []
        records = payload if isinstance(payload, list) else payload.get("trades") or payload.get("items") or []
        items: list[dict[str, object]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "market_id": market_id,
                    "price": self._price_value(item),
                    "size": item.get("qty") or item.get("quantity") or item.get("size"),
                    "timestamp": item.get("transactTime") or item.get("createdAt") or item.get("timestamp"),
                }
            )
        return items

    async def get_market_prices(self, market_id: str) -> dict[str, float | None]:
        market = await self.get_market(market_id)
        return {
            "yes_price": market.yes_price if market is not None else None,
            "no_price": market.no_price if market is not None else None,
        }

    async def get_linked_markets(self, market_id: str | None = None) -> dict[str, list[str]]:
        markets = await self.list_markets()
        groups: dict[str, list[str]] = {}
        for item in markets:
            if item.linked_group is None:
                continue
            groups.setdefault(item.linked_group, []).append(item.market_id)
        if market_id is None:
            return groups
        return {key: value for key, value in groups.items() if market_id in value}

    async def health_check(self) -> dict[str, object]:
        return self._runtime.build_health(
            max_data_age_seconds=self.settings.polymarket_max_data_age_seconds,
            metadata={"provider_mode": "real", "base_url": self.settings.polymarket_base_url},
            configured=self.is_configured,
        )

    def should_fallback_on_empty(self, method_name: str, value: object) -> bool:
        return not self.is_configured

    async def _request_json(self, path: str) -> Any:
        started_at = utc_now()
        try:
            async with self._get_client() as client:
                response = await client.get(path)
                response.raise_for_status()
                payload = response.json()
            self._runtime.record_success(started_at=started_at)
            return payload
        except Exception:
            self._runtime.record_failure()
            raise

    def _get_client(self):
        if self._client is not None:
            return ExistingAsyncClientContext(self._client)
        return httpx.AsyncClient(
            base_url=self.settings.polymarket_base_url.rstrip("/"),
            timeout=max(self.settings.polymarket_timeout_ms / 1000.0, 0.5),
            headers={"Accept": "application/json"},
        )

    def _normalize_market(self, raw: dict[str, object]) -> PolymarketMarket | None:
        market_id = str(raw.get("slug") or raw.get("marketSlug") or raw.get("id") or raw.get("market_id") or "").strip()
        if not market_id:
            return None
        yes_price = (
            safe_float(raw.get("yes_price"))
            or safe_float(raw.get("yesPrice"))
            or safe_float(raw.get("longPrice"))
            or safe_float(((raw.get("stats") or {}) if isinstance(raw.get("stats"), dict) else {}).get("currentPx", {}).get("value") if isinstance(((raw.get("stats") or {}) if isinstance(raw.get("stats"), dict) else {}).get("currentPx"), dict) else None)
        )
        no_price = (
            safe_float(raw.get("no_price"))
            or safe_float(raw.get("noPrice"))
            or safe_float(raw.get("shortPrice"))
        )
        if no_price is None and yes_price is not None and 0.0 <= yes_price <= 1.0:
            no_price = round(1.0 - yes_price, 6)
        linked_group = str(raw.get("eventSlug") or raw.get("event_slug") or raw.get("seriesSlug") or "").strip() or None
        status = str(raw.get("status") or raw.get("state") or "open").lower()
        title = str(raw.get("question") or raw.get("title") or raw.get("name") or market_id)
        category = str(raw.get("category") or raw.get("tag") or "general")
        updated_at = ensure_datetime(raw.get("updatedAt") or raw.get("lastTradeTime") or raw.get("createdAt")) or utc_now()
        return PolymarketMarket(
            market_id=market_id,
            title=title,
            category=category,
            event_slug=str(raw.get("eventSlug") or raw.get("event_slug") or linked_group or market_id),
            status=status,
            close_time=ensure_datetime(raw.get("endDate") or raw.get("closeTime") or raw.get("closedAt")),
            last_updated_at=updated_at,
            yes_price=yes_price,
            no_price=no_price,
            linked_group=linked_group,
            linked_rule="event_slug_group",
            metadata={
                "source": "polymarket_real",
                "source_id": raw.get("id"),
                "description": raw.get("description"),
                "diagnostics": {"raw_status": raw.get("status") or raw.get("state")},
            },
        )

    def _price_value(self, item: dict[str, object]) -> float | None:
        px = item.get("px")
        if isinstance(px, dict):
            return safe_float(px.get("value"))
        return safe_float(item.get("price") or px)

    def _quantity_value(self, item: dict[str, object]) -> float:
        return safe_float(item.get("qty") or item.get("quantity") or item.get("size")) or 0.0


class FallbackPolymarketProvider:
    def __init__(self, *, real: RealPolymarketProvider, mock: object, allow_mock_fallback: bool) -> None:
        self._adapter = FallbackProviderAdapter(
            real=real,
            mock=mock,
            allow_mock_fallback=allow_mock_fallback,
            empty_fallback_methods={"list_markets", "get_market", "get_orderbook", "get_market_prices", "get_linked_markets"},
        )

    async def list_markets(self) -> list[PolymarketMarket]:
        return await self._adapter.call("list_markets")

    async def get_market(self, market_id: str) -> PolymarketMarket | None:
        return await self._adapter.call("get_market", market_id)

    async def get_orderbook(self, market_id: str) -> PolymarketOrderBook | None:
        return await self._adapter.call("get_orderbook", market_id)

    async def get_recent_trades(self, market_id: str) -> list[dict[str, object]]:
        return await self._adapter.call("get_recent_trades", market_id)

    async def get_market_prices(self, market_id: str) -> dict[str, float | None]:
        return await self._adapter.call("get_market_prices", market_id)

    async def get_linked_markets(self, market_id: str | None = None) -> dict[str, list[str]]:
        return await self._adapter.call("get_linked_markets", market_id)

    async def health_check(self) -> dict[str, object]:
        return await self._adapter.health_check()


def build_polymarket_provider(*, settings: Settings | None = None, client: httpx.AsyncClient | None = None, mock_provider: object | None = None):
    resolved = settings or get_settings()
    mock = mock_provider or MockPolymarketProvider()
    mode = resolved.polymarket_provider_mode
    if mode == "mock":
        return mock
    real = RealPolymarketProvider(settings=resolved, client=client)
    if mode == "real":
        return real
    return FallbackPolymarketProvider(
        real=real,
        mock=mock,
        allow_mock_fallback=local_fallback_allowed(resolved),
    )

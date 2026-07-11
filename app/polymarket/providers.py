from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.config.settings import Settings, get_settings
from app.polymarket.types import PolymarketBookLevel, PolymarketMarket, PolymarketOrderBook
from app.providers.common import (
    ExistingAsyncClientContext,
    FallbackProviderAdapter,
    ProviderRuntimeState,
    ensure_datetime,
    local_fallback_allowed,
    safe_float,
    utc_now,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _TokenBook:
    token_id: str
    condition_id: str | None
    bids: list[PolymarketBookLevel]
    asks: list[PolymarketBookLevel]
    captured_at: datetime
    source_hash: str | None = None
    source: str = "clob_rest"


def _first_float(*values: object) -> float | None:
    for value in values:
        parsed = safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _venue_time(value: object) -> datetime | None:
    parsed = ensure_datetime(value)
    if parsed is not None:
        return parsed
    numeric = safe_float(value)
    if numeric is None:
        return None
    if numeric > 10_000_000_000:
        numeric /= 1000.0
    try:
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _fee_rate_for_category(category: str, *, enabled: bool) -> float:
    if not enabled:
        return 0.0
    normalized = category.strip().lower()
    if normalized in {"crypto", "cryptocurrency"}:
        return 0.07
    if normalized in {"finance", "politics", "mentions", "tech", "technology"}:
        return 0.04
    if normalized in {"sports", "economics", "culture", "weather"}:
        return 0.05
    if normalized in {"geopolitics", "geopolitical"}:
        return 0.0
    return 0.05


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
                close_time=now + timedelta(days=30),
                last_updated_at=now,
                yes_price=0.58,
                no_price=0.46,
                linked_group="us-election-primary",
                linked_rule="yes_no_sum",
                condition_id="mock_condition_election",
                yes_token_id="mock_yes_election",
                no_token_id="mock_no_election",
                liquidity_usd=15000.0,
                source="mock",
            ),
            "pm_rate_cut_yes": PolymarketMarket(
                market_id="pm_rate_cut_yes",
                title="Will the central bank cut rates this quarter?",
                category="macro",
                event_slug="rate-cut-quarter",
                status="open",
                close_time=now + timedelta(days=30),
                last_updated_at=now,
                yes_price=0.41,
                no_price=0.55,
                linked_group="macro-rate",
                linked_rule="yes_no_sum",
                condition_id="mock_condition_rate",
                yes_token_id="mock_yes_rate",
                no_token_id="mock_no_rate",
                liquidity_usd=7000.0,
                source="mock",
            ),
            "pm_crypto_etf_approval": PolymarketMarket(
                market_id="pm_crypto_etf_approval",
                title="Will a major crypto ETF be approved this month?",
                category="crypto",
                event_slug="crypto-etf-approval",
                status="open",
                close_time=now + timedelta(days=30),
                last_updated_at=now,
                yes_price=0.67,
                no_price=0.29,
                linked_group="crypto-policy",
                linked_rule="bounded_pair_sum",
                condition_id="mock_condition_etf",
                yes_token_id="mock_yes_etf",
                no_token_id="mock_no_etf",
                liquidity_usd=7000.0,
                fees_enabled=True,
                fee_rate=0.07,
                source="mock",
            ),
            "pm_crypto_etf_delay": PolymarketMarket(
                market_id="pm_crypto_etf_delay",
                title="Will a major crypto ETF approval be delayed this month?",
                category="crypto",
                event_slug="crypto-etf-delay",
                status="open",
                close_time=now + timedelta(days=30),
                last_updated_at=now,
                yes_price=0.44,
                no_price=0.52,
                linked_group="crypto-policy",
                linked_rule="bounded_pair_sum",
                condition_id="mock_condition_etf_delay",
                yes_token_id="mock_yes_etf_delay",
                no_token_id="mock_no_etf_delay",
                liquidity_usd=7000.0,
                fees_enabled=True,
                fee_rate=0.07,
                source="mock",
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
        spread = 0.02 if market.market_id == "pm_us_election_yes" else 0.015
        yes_mid = market.yes_price or 0.5
        no_mid = market.no_price or 0.5
        yes_bids = [PolymarketBookLevel(max(yes_mid - spread, 0.01), 5000.0)]
        yes_asks = [PolymarketBookLevel(min(yes_mid + spread, 0.99), 4500.0)]
        no_bids = [PolymarketBookLevel(max(no_mid - spread, 0.01), 5000.0)]
        no_asks = [PolymarketBookLevel(min(no_mid + spread, 0.99), 4500.0)]
        return _combine_books(
            market,
            _TokenBook(market.yes_token_id or "mock_yes", market.condition_id, yes_bids, yes_asks, market.last_updated_at, source="mock"),
            _TokenBook(market.no_token_id or "mock_no", market.condition_id, no_bids, no_asks, market.last_updated_at, source="mock"),
            source="mock",
        )

    async def get_recent_trades(self, market_id: str) -> list[dict[str, object]]:
        market = self._markets.get(market_id)
        if market is None:
            return []
        return [{"market_id": market_id, "price": market.yes_price, "size": 250.0, "timestamp": market.last_updated_at.isoformat(), "outcome": "Yes"}]

    async def get_market_prices(self, market_id: str) -> dict[str, float | None]:
        market = self._markets.get(market_id)
        if market is None:
            return {"yes_price": None, "no_price": None}
        return {"yes_price": market.yes_price, "no_price": market.no_price}

    async def get_linked_markets(self, market_id: str | None = None) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for item in self._markets.values():
            if item.linked_group is not None:
                groups.setdefault(item.linked_group, []).append(item.market_id)
        if market_id is None:
            return groups
        return {key: value for key, value in groups.items() if market_id in value}

    async def health_check(self) -> dict[str, object]:
        return {
            "status": "healthy",
            "success_rate": 1.0,
            "stale_data_flag": False,
            "error_count": 0,
            "metadata": {"provider_mode": "mock", "source_is_mock": True, "stream_status": "mock"},
        }


class RealPolymarketProvider:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        gamma_client: httpx.AsyncClient | None = None,
        clob_client: httpx.AsyncClient | None = None,
        data_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._gamma_client = gamma_client or client
        self._clob_client = clob_client or client
        self._data_client = data_client or client
        self._runtime = ProviderRuntimeState()
        self._markets: dict[str, PolymarketMarket] = {}
        self._aliases: dict[str, str] = {}
        self._token_books: dict[str, _TokenBook] = {}
        self._book_lock = asyncio.Lock()
        self._stream_task: asyncio.Task[None] | None = None
        self._stream_stop = asyncio.Event()
        self._stream_asset_ids: list[str] = []
        self.stream_status = "disabled" if not self.settings.polymarket_stream_enabled else "stopped"
        self.last_stream_message_at: datetime | None = None
        self.stream_reconnect_count = 0

    @property
    def has_successful_fetch(self) -> bool:
        return self._runtime.has_successful_fetch

    @property
    def is_configured(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.settings.polymarket_base_url,
                self.settings.polymarket_clob_base_url,
                self.settings.polymarket_data_base_url,
            )
        )

    async def list_markets(self) -> list[PolymarketMarket]:
        remaining = max(self.settings.polymarket_market_limit, 1)
        offset = 0
        markets: list[PolymarketMarket] = []
        while remaining > 0:
            page_size = min(remaining, 100)
            payload = await self._request_json(
                "gamma",
                "/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": page_size,
                    "offset": offset,
                    "order": "volume_24hr",
                    "ascending": "false",
                },
            )
            records = payload if isinstance(payload, list) else payload.get("markets") or payload.get("items") or payload.get("data") or []
            normalized_page: list[PolymarketMarket] = []
            for record in records:
                if not isinstance(record, dict):
                    continue
                market = self._normalize_market(record)
                if market is not None:
                    normalized_page.append(market)
                    self._cache_market(market)
            markets.extend(normalized_page)
            if len(records) < page_size:
                break
            remaining -= page_size
            offset += page_size
        return markets

    async def get_market(self, market_id: str) -> PolymarketMarket | None:
        cached = self._resolve_market(market_id)
        if cached is not None:
            return cached
        payload = await self._request_json("gamma", "/markets", params={"slug": market_id, "limit": 1})
        records = payload if isinstance(payload, list) else payload.get("markets") or payload.get("data") or []
        record = records[0] if isinstance(records, list) and records else None
        if not isinstance(record, dict) and market_id.isdigit():
            payload = await self._request_json("gamma", f"/markets/{market_id}")
            record = payload if isinstance(payload, dict) else None
        if not isinstance(record, dict):
            return None
        market = self._normalize_market(record)
        if market is not None:
            self._cache_market(market)
        return market

    async def get_orderbook(self, market_id: str) -> PolymarketOrderBook | None:
        market = self._resolve_market(market_id) or await self.get_market(market_id)
        if market is None or not market.yes_token_id or not market.no_token_id:
            return None

        stream_book = await self._combined_stream_book(market)
        if stream_book is not None:
            return stream_book

        yes_payload, no_payload = await asyncio.gather(
            self._request_json("clob", "/book", params={"token_id": market.yes_token_id}),
            self._request_json("clob", "/book", params={"token_id": market.no_token_id}),
        )
        yes_book = self._normalize_token_book(yes_payload, expected_token_id=market.yes_token_id)
        no_book = self._normalize_token_book(no_payload, expected_token_id=market.no_token_id)
        if yes_book is None or no_book is None:
            return None
        async with self._book_lock:
            self._token_books[yes_book.token_id] = yes_book
            self._token_books[no_book.token_id] = no_book
        return _combine_books(market, yes_book, no_book, source="clob_rest")

    async def get_recent_trades(self, market_id: str) -> list[dict[str, object]]:
        market = self._resolve_market(market_id) or await self.get_market(market_id)
        if market is None or market.condition_id is None:
            return []
        try:
            payload = await self._request_json(
                "data",
                "/trades",
                params={"market": market.condition_id, "limit": 100, "offset": 0, "takerOnly": "false"},
            )
        except (httpx.HTTPError, ValueError):
            return []
        records = payload if isinstance(payload, list) else payload.get("data") or payload.get("trades") or []
        items: list[dict[str, object]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            timestamp = _venue_time(item.get("timestamp") or item.get("match_time") or item.get("createdAt"))
            items.append(
                {
                    "market_id": market.market_id,
                    "condition_id": market.condition_id,
                    "token_id": item.get("asset") or item.get("asset_id"),
                    "price": _first_float(item.get("price"), item.get("lastTradePrice")),
                    "size": _first_float(item.get("size"), item.get("quantity")),
                    "side": item.get("side"),
                    "outcome": item.get("outcome"),
                    "timestamp": timestamp.isoformat() if timestamp is not None else None,
                    "source": "polymarket_data_api",
                }
            )
        return items

    async def get_market_prices(self, market_id: str) -> dict[str, float | None]:
        orderbook = await self.get_orderbook(market_id)
        market = self._resolve_market(market_id)
        if orderbook is None:
            return {
                "yes_price": market.yes_price if market is not None else None,
                "no_price": market.no_price if market is not None else None,
            }
        return {
            "yes_price": _midpoint(orderbook.yes_bid, orderbook.yes_ask),
            "no_price": _midpoint(orderbook.no_bid, orderbook.no_ask),
        }

    async def get_linked_markets(self, market_id: str | None = None) -> dict[str, list[str]]:
        markets = list(self._markets.values()) or await self.list_markets()
        groups: dict[str, list[str]] = {}
        for item in markets:
            if item.linked_group is not None:
                groups.setdefault(item.linked_group, []).append(item.market_id)
        if market_id is None:
            return groups
        return {key: value for key, value in groups.items() if market_id in value}

    async def start(self) -> None:
        if not self.settings.polymarket_stream_enabled or self._stream_task is not None:
            return
        if not self._markets:
            await self.list_markets()
        ordered = sorted(self._markets.values(), key=self._stream_priority, reverse=True)
        asset_ids: list[str] = []
        for market in ordered:
            for token_id in (market.yes_token_id, market.no_token_id):
                if token_id and token_id not in asset_ids:
                    asset_ids.append(token_id)
                if len(asset_ids) >= self.settings.polymarket_stream_max_assets:
                    break
            if len(asset_ids) >= self.settings.polymarket_stream_max_assets:
                break
        if not asset_ids:
            self.stream_status = "degraded"
            return
        self._stream_asset_ids = asset_ids
        self._stream_stop.clear()
        self._stream_task = asyncio.create_task(self._run_stream(), name="polymarket-market-stream")

    async def stop(self) -> None:
        self._stream_stop.set()
        if self._stream_task is not None:
            self._stream_task.cancel()
            await asyncio.gather(self._stream_task, return_exceptions=True)
            self._stream_task = None
        self.stream_status = "stopped"

    async def health_check(self) -> dict[str, object]:
        payload = self._runtime.build_health(
            max_data_age_seconds=self.settings.polymarket_max_data_age_seconds,
            metadata={
                "provider_mode": "real",
                "source_is_mock": False,
                "gamma_base_url": self.settings.polymarket_base_url,
                "clob_base_url": self.settings.polymarket_clob_base_url,
                "data_base_url": self.settings.polymarket_data_base_url,
                "stream_status": self.stream_status,
                "stream_asset_count": len(self._stream_asset_ids),
                "last_stream_message_at": self.last_stream_message_at,
                "stream_reconnect_count": self.stream_reconnect_count,
            },
            configured=self.is_configured,
        )
        if self.settings.polymarket_stream_enabled:
            stream_stale = self.last_stream_message_at is None or (
                utc_now() - self.last_stream_message_at
            ).total_seconds() > self.settings.polymarket_stream_stale_seconds
            payload["metadata"]["stream_stale"] = stream_stale
            if (self.stream_status != "connected" or stream_stale) and payload["status"] == "healthy":
                payload["status"] = "degraded"
        return payload

    def should_fallback_on_empty(self, method_name: str, value: object) -> bool:
        return not self.is_configured

    async def _request_json(
        self,
        api: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> Any:
        started_at = utc_now()
        try:
            async with self._get_client(api) as client:
                response = await client.get(path, params=params)
                response.raise_for_status()
                payload = response.json()
            self._runtime.record_success(started_at=started_at)
            return payload
        except Exception as exc:
            self._runtime.record_failure(exc)
            raise

    def _get_client(self, api: str):
        injected = {
            "gamma": self._gamma_client,
            "clob": self._clob_client,
            "data": self._data_client,
        }[api]
        if injected is not None:
            return ExistingAsyncClientContext(injected)
        base_url = {
            "gamma": self.settings.polymarket_base_url,
            "clob": self.settings.polymarket_clob_base_url,
            "data": self.settings.polymarket_data_base_url,
        }[api]
        return httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=max(self.settings.polymarket_timeout_ms / 1000.0, 0.5),
            headers={"Accept": "application/json", "User-Agent": "trading-system-polymarket-research/1.0"},
        )

    def _normalize_market(self, raw: dict[str, object]) -> PolymarketMarket | None:
        market_id = str(raw.get("slug") or raw.get("marketSlug") or raw.get("id") or raw.get("market_id") or "").strip()
        if not market_id:
            return None
        outcomes = [str(item).strip().lower() for item in _json_list(raw.get("outcomes"))]
        prices = _json_list(raw.get("outcomePrices"))
        tokens = [str(item).strip() for item in _json_list(raw.get("clobTokenIds"))]
        yes_index = outcomes.index("yes") if "yes" in outcomes else 0
        no_index = outcomes.index("no") if "no" in outcomes else 1
        yes_price = _first_float(
            prices[yes_index] if yes_index < len(prices) else None,
            raw.get("yes_price"),
            raw.get("yesPrice"),
            raw.get("lastTradePrice"),
        )
        no_price = _first_float(
            prices[no_index] if no_index < len(prices) else None,
            raw.get("no_price"),
            raw.get("noPrice"),
        )
        if no_price is None and yes_price is not None and 0.0 <= yes_price <= 1.0:
            no_price = round(1.0 - yes_price, 6)
        condition_id = str(raw.get("conditionId") or raw.get("condition_id") or "").strip() or None
        event_slug = str(raw.get("eventSlug") or raw.get("event_slug") or "").strip()
        events = raw.get("events")
        if not event_slug and isinstance(events, list) and events and isinstance(events[0], dict):
            event_slug = str(events[0].get("slug") or events[0].get("ticker") or "").strip()
        event_slug = event_slug or market_id
        linked_group = event_slug
        closed = bool(raw.get("closed", False))
        active = bool(raw.get("active", not closed))
        status = "open" if active and not closed else "closed"
        title = str(raw.get("question") or raw.get("title") or raw.get("name") or market_id)
        category = str(raw.get("category") or raw.get("tag") or "general")
        updated_at = ensure_datetime(raw.get("updatedAt") or raw.get("lastTradeTime") or raw.get("createdAt")) or utc_now()
        start_time = ensure_datetime(raw.get("eventStartTime") or raw.get("startDate"))
        close_time = ensure_datetime(raw.get("endDate") or raw.get("closeTime") or raw.get("closedAt"))
        duration_minutes = None
        if start_time is not None and close_time is not None:
            duration_minutes = max((close_time - start_time).total_seconds() / 60.0, 0.0)
        fees_enabled = bool(raw.get("feesEnabled", False))
        fee_rate = _first_float(raw.get("feeRate"), raw.get("fee_rate"))
        if fee_rate is None:
            fee_rate = _fee_rate_for_category(category, enabled=fees_enabled)
        yes_token_id = tokens[yes_index] if yes_index < len(tokens) else None
        no_token_id = tokens[no_index] if no_index < len(tokens) else None
        threshold = _first_float(raw.get("lowerBound"), raw.get("upperBound"), raw.get("threshold"))
        return PolymarketMarket(
            market_id=market_id,
            title=title,
            category=category,
            event_slug=event_slug,
            status=status,
            close_time=close_time,
            last_updated_at=updated_at,
            yes_price=yes_price,
            no_price=no_price,
            linked_group=linked_group,
            linked_rule="event_slug_group",
            condition_id=condition_id,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            liquidity_usd=_first_float(raw.get("liquidityNum"), raw.get("liquidity")),
            fees_enabled=fees_enabled,
            fee_rate=max(fee_rate, 0.0),
            source="polymarket_gamma",
            metadata={
                "source": "polymarket_gamma",
                "source_id": raw.get("id"),
                "description": raw.get("description"),
                "resolution_source": raw.get("resolutionSource"),
                "enable_order_book": raw.get("enableOrderBook"),
                "neg_risk": raw.get("negRisk"),
                "start_time": start_time,
                "duration_minutes": duration_minutes,
                "threshold_price": threshold,
                "series_slug": raw.get("seriesSlug"),
                "question_id": raw.get("questionID"),
                "diagnostics": {
                    "raw_status": raw.get("status"),
                    "active": active,
                    "closed": closed,
                    "outcomes": outcomes,
                },
            },
        )

    def _normalize_token_book(self, raw: object, *, expected_token_id: str) -> _TokenBook | None:
        if not isinstance(raw, dict):
            return None
        token_id = str(raw.get("asset_id") or expected_token_id)
        return _TokenBook(
            token_id=token_id,
            condition_id=str(raw.get("market") or "").strip() or None,
            bids=_levels(raw.get("bids"), descending=True, limit=self.settings.polymarket_book_depth_levels),
            asks=_levels(raw.get("asks"), descending=False, limit=self.settings.polymarket_book_depth_levels),
            captured_at=_venue_time(raw.get("timestamp")) or utc_now(),
            source_hash=str(raw.get("hash") or "").strip() or None,
            source="clob_rest",
        )

    def _cache_market(self, market: PolymarketMarket) -> None:
        self._markets[market.market_id] = market
        for alias in (market.market_id, market.condition_id, market.yes_token_id, market.no_token_id):
            if alias:
                self._aliases[alias] = market.market_id
        source_id = market.metadata.get("source_id")
        if source_id is not None:
            self._aliases[str(source_id)] = market.market_id

    def _resolve_market(self, identifier: str) -> PolymarketMarket | None:
        market_id = self._aliases.get(identifier, identifier)
        return self._markets.get(market_id)

    async def _combined_stream_book(self, market: PolymarketMarket) -> PolymarketOrderBook | None:
        if not self.settings.polymarket_stream_enabled or not market.yes_token_id or not market.no_token_id:
            return None
        async with self._book_lock:
            yes_book = self._token_books.get(market.yes_token_id)
            no_book = self._token_books.get(market.no_token_id)
        if yes_book is None or no_book is None:
            return None
        captured_at = min(yes_book.captured_at, no_book.captured_at)
        if (utc_now() - captured_at).total_seconds() > self.settings.polymarket_stream_stale_seconds:
            return None
        return _combine_books(market, yes_book, no_book, source="clob_websocket")

    async def _run_stream(self) -> None:
        retry_delay = 1.0
        while not self._stream_stop.is_set():
            self.stream_status = "connecting"
            try:
                async with websockets.connect(
                    self.settings.polymarket_ws_url,
                    ping_interval=None,
                    close_timeout=5,
                    max_size=2**22,
                ) as websocket:
                    await websocket.send(
                        json.dumps(
                            {
                                "assets_ids": self._stream_asset_ids,
                                "type": "market",
                                "custom_feature_enabled": True,
                            }
                        )
                    )
                    self.stream_status = "connected"
                    retry_delay = 1.0
                    while not self._stream_stop.is_set():
                        try:
                            raw_message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                        except TimeoutError:
                            await websocket.send("PING")
                            continue
                        if raw_message == "PONG":
                            continue
                        try:
                            payload = json.loads(raw_message)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        self.last_stream_message_at = utc_now()
                        await self._handle_stream_payload(payload)
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                self.stream_status = "degraded"
                self.stream_reconnect_count += 1
                self._runtime.record_failure(exc)
                logger.warning("polymarket market stream disconnected error=%s", exc)
            if not self._stream_stop.is_set():
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2.0, 10.0)

    async def _handle_stream_payload(self, payload: object) -> None:
        if isinstance(payload, list):
            for item in payload:
                await self._handle_stream_payload(item)
            return
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("event_type") or payload.get("type") or "")
        if event_type == "book":
            token_id = str(payload.get("asset_id") or "")
            if not token_id:
                return
            book = self._normalize_token_book(payload, expected_token_id=token_id)
            if book is not None:
                book.source = "clob_websocket"
                async with self._book_lock:
                    self._token_books[token_id] = book
            return
        if event_type != "price_change":
            return
        changes = payload.get("price_changes")
        if not isinstance(changes, list):
            changes = [payload]
        timestamp = _venue_time(payload.get("timestamp")) or utc_now()
        async with self._book_lock:
            for change in changes:
                if not isinstance(change, dict):
                    continue
                token_id = str(change.get("asset_id") or payload.get("asset_id") or "")
                book = self._token_books.get(token_id)
                if not token_id or book is None:
                    continue
                price = safe_float(change.get("price"))
                size = safe_float(change.get("size"))
                side = str(change.get("side") or "").upper()
                if price is None or size is None or side not in {"BUY", "SELL"}:
                    continue
                target = list(book.bids if side == "BUY" else book.asks)
                target = [level for level in target if level.price != price]
                if size > 0:
                    target.append(PolymarketBookLevel(price=price, size=size))
                target.sort(key=lambda item: item.price, reverse=side == "BUY")
                target = target[: self.settings.polymarket_book_depth_levels]
                if side == "BUY":
                    book.bids = target
                else:
                    book.asks = target
                book.captured_at = timestamp
                book.source = "clob_websocket"

    def _stream_priority(self, market: PolymarketMarket) -> tuple[int, float]:
        text = f"{market.title} {market.event_slug} {market.metadata.get('series_slug', '')}".lower()
        crypto_short = int(any(token in text for token in ("bitcoin", "btc", "ethereum", "eth")))
        return crypto_short, market.liquidity_usd or 0.0


class FallbackPolymarketProvider:
    def __init__(self, *, real: RealPolymarketProvider, mock: object, allow_mock_fallback: bool) -> None:
        self.real = real
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

    async def start(self) -> None:
        try:
            await self.real.start()
        except Exception:
            if not self._adapter.allow_mock_fallback:
                raise
            logger.warning("polymarket real stream unavailable; mock fallback remains active")

    async def stop(self) -> None:
        await self.real.stop()

    async def health_check(self) -> dict[str, object]:
        return await self._adapter.health_check()


def _levels(raw: object, *, descending: bool, limit: int) -> list[PolymarketBookLevel]:
    if not isinstance(raw, list):
        return []
    levels: list[PolymarketBookLevel] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        price = _first_float(item.get("price"), item.get("px"))
        size = _first_float(item.get("size"), item.get("qty"), item.get("quantity"))
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        levels.append(PolymarketBookLevel(price=price, size=size))
    levels.sort(key=lambda item: item.price, reverse=descending)
    return levels[: max(limit, 1)]


def _midpoint(bid: float | None, ask: float | None) -> float | None:
    if bid is not None and ask is not None:
        return round((bid + ask) / 2.0, 8)
    return ask if ask is not None else bid


def _spread_bps(bids: list[PolymarketBookLevel], asks: list[PolymarketBookLevel]) -> float | None:
    if not bids or not asks:
        return None
    midpoint = (bids[0].price + asks[0].price) / 2.0
    if midpoint <= 0:
        return None
    return max((asks[0].price - bids[0].price) / midpoint * 10000.0, 0.0)


def _combine_books(
    market: PolymarketMarket,
    yes_book: _TokenBook,
    no_book: _TokenBook,
    *,
    source: str,
) -> PolymarketOrderBook:
    yes_spread = _spread_bps(yes_book.bids, yes_book.asks)
    no_spread = _spread_bps(no_book.bids, no_book.asks)
    spread_values = [value for value in (yes_spread, no_spread) if value is not None]
    depth_usd = sum(level.price * level.size for level in [*yes_book.bids, *yes_book.asks, *no_book.bids, *no_book.asks])
    captured_at = min(yes_book.captured_at, no_book.captured_at)
    return PolymarketOrderBook(
        market_id=market.market_id,
        yes_bid=yes_book.bids[0].price if yes_book.bids else None,
        yes_ask=yes_book.asks[0].price if yes_book.asks else None,
        no_bid=no_book.bids[0].price if no_book.bids else None,
        no_ask=no_book.asks[0].price if no_book.asks else None,
        depth_usd=round(depth_usd, 6),
        spread_bps=round(max(spread_values), 6) if spread_values else None,
        captured_at=captured_at,
        yes_bids=list(yes_book.bids),
        yes_asks=list(yes_book.asks),
        no_bids=list(no_book.bids),
        no_asks=list(no_book.asks),
        source=source,
        source_hash=(
            f"{yes_book.source_hash or ''}:{no_book.source_hash or ''}"
            if yes_book.source_hash or no_book.source_hash
            else None
        ),
        metadata={
            "condition_id": market.condition_id,
            "yes_token_id": market.yes_token_id,
            "no_token_id": market.no_token_id,
            "yes_captured_at": yes_book.captured_at,
            "no_captured_at": no_book.captured_at,
            "yes_spread_bps": yes_spread,
            "no_spread_bps": no_spread,
        },
    )


def build_polymarket_provider(
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    mock_provider: object | None = None,
):
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

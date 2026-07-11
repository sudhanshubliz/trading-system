from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import Settings, get_settings
from app.db.models import MarketSnapshot
from app.db.session import SessionLocal
from app.market_data.binance_rest import BinanceFuturesRestClient, BinanceRestClient, BinanceRestError
from app.market_data.binance_ws import BinanceWebSocketClient
from app.market_data.cache import CandleCache, FundingCache, OrderBookCache, PriceHistoryCache, TickerCache, TradePrintCache
from app.market_data.schemas import (
    extract_stream_payload,
    infer_event_type,
    infer_symbol,
    normalize_symbol,
    normalize_timeframe,
    parse_funding_history_item,
    parse_funding_snapshot,
    parse_float,
    parse_order_book_snapshot,
    parse_order_book_top,
    parse_rest_candle,
    parse_trade_print,
    parse_ws_candle,
)
from app.market_data.types import Candle, FundingRatePoint, FundingSnapshot, MarketDataHealth, OrderBookSnapshot, PricePoint, SymbolHealth, TickerSnapshot, TradePrint

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MarketDataService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.supported_symbols = [normalize_symbol(symbol) for symbol in self.settings.market_data_symbols]
        self.supported_timeframes = [
            normalize_timeframe(timeframe) for timeframe in self.settings.market_data_timeframes
        ]
        self.rest_client = BinanceRestClient(self.settings.binance_rest_base_url)
        self.futures_rest_client = BinanceFuturesRestClient(self.settings.binance_futures_rest_base_url)
        self.ws_client = BinanceWebSocketClient(
            self.settings.binance_ws_base_url,
            self.supported_symbols,
            self.supported_timeframes,
        )
        self.candle_cache = CandleCache(limit=self.settings.market_data_candle_limit)
        self.orderbook_cache = OrderBookCache()
        self.ticker_cache = TickerCache(self.supported_symbols)
        self.trade_cache = TradePrintCache(limit=self.settings.market_data_trade_cache_limit)
        self.price_history_cache = PriceHistoryCache(limit=self.settings.market_data_price_history_limit)
        self.funding_cache = FundingCache(history_limit=self.settings.market_data_funding_cache_limit)
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._fallback_active = False
        self._last_persisted_at: dict[str, datetime] = {}

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        self._tasks = [
            asyncio.create_task(self._bootstrap_loop(), name="market-data-bootstrap"),
            asyncio.create_task(self.ws_client.start(self._handle_ws_message), name="market-data-ws"),
            asyncio.create_task(self._health_monitor_loop(), name="market-data-health-monitor"),
            asyncio.create_task(self._fallback_loop(), name="market-data-fallback"),
        ]
        logger.info(
            "market data service started symbols=%s timeframes=%s",
            ",".join(self.supported_symbols),
            ",".join(self.supported_timeframes),
        )

    async def stop(self) -> None:
        if not self._started:
            await self.rest_client.close()
            return

        await self.ws_client.stop()

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        await self.rest_client.close()
        await self.futures_rest_client.close()
        self._started = False
        logger.info("market data service stopped")

    def supports_symbol(self, symbol: str) -> bool:
        return normalize_symbol(symbol) in self.supported_symbols

    def supports_timeframe(self, timeframe: str) -> bool:
        return normalize_timeframe(timeframe) in self.supported_timeframes

    async def seed_initial_data(self) -> None:
        for symbol in self.supported_symbols:
            for timeframe in self.supported_timeframes:
                try:
                    raw_candles = await self.rest_client.get_klines(
                        symbol,
                        timeframe,
                        limit=self.settings.market_data_candle_limit,
                    )
                except BinanceRestError:
                    logger.exception("failed to seed candles symbol=%s timeframe=%s", symbol, timeframe)
                    continue

                candles = [parse_rest_candle(item) for item in raw_candles]
                async with self._lock:
                    self.candle_cache.seed(symbol, timeframe, candles, updated_at=utc_now())

            await self._refresh_symbol_from_rest(symbol, persist=True)

    async def get_health(self) -> MarketDataHealth:
        now = utc_now()
        async with self._lock:
            snapshots = {snapshot.symbol: snapshot for snapshot in self.ticker_cache.all()}
            last_ws_message_at = self.ws_client.last_message_at
            fallback_active = self._fallback_active

        websocket_status = self._resolve_websocket_status(now, last_ws_message_at)
        symbols: dict[str, SymbolHealth] = {}
        all_fresh = websocket_status == "ok"

        for symbol in self.supported_symbols:
            snapshot = snapshots.get(symbol)
            ticker_updated_at = snapshot.ticker_updated_at if snapshot else None
            orderbook_updated_at = snapshot.orderbook_updated_at if snapshot else None
            ticker_fresh = self._is_fresh(ticker_updated_at, self.settings.market_data_ticker_freshness_ms, now)
            orderbook_fresh = self._is_fresh(
                orderbook_updated_at,
                self.settings.market_data_orderbook_freshness_ms,
                now,
            )
            candles_fresh = {
                timeframe: self._is_fresh(
                    self.candle_cache.last_update(symbol, timeframe),
                    self.settings.market_data_candle_freshness_ms,
                    now,
                )
                for timeframe in self.supported_timeframes
            }

            symbol_health = SymbolHealth(
                symbol=symbol,
                ticker_fresh=ticker_fresh,
                orderbook_fresh=orderbook_fresh,
                candles_fresh=candles_fresh,
                last_price=snapshot.last_price if snapshot else None,
                ticker_updated_at=ticker_updated_at,
                orderbook_updated_at=orderbook_updated_at,
            )
            symbols[symbol] = symbol_health
            if not ticker_fresh or not orderbook_fresh or not all(candles_fresh.values()):
                all_fresh = False

        status = "ok" if all_fresh and not fallback_active else "degraded"

        return MarketDataHealth(
            status=status,
            websocket_status=websocket_status,
            fallback_active=fallback_active,
            supported_symbols=self.supported_symbols,
            supported_timeframes=self.supported_timeframes,
            last_ws_message_at=last_ws_message_at,
            symbols=symbols,
            timestamp=now,
        )

    async def get_latest_snapshots(self) -> list[TickerSnapshot]:
        async with self._lock:
            snapshots = self.ticker_cache.all()
        return sorted(snapshots, key=lambda item: item.symbol)

    async def get_snapshot(self, symbol: str) -> TickerSnapshot | None:
        if not self.supports_symbol(symbol):
            return None

        async with self._lock:
            return self.ticker_cache.get(symbol)

    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle] | None:
        if not self.supports_symbol(symbol) or not self.supports_timeframe(timeframe):
            return None

        async with self._lock:
            return self.candle_cache.get(symbol, timeframe)

    async def get_futures_candles(self, symbol: str, timeframe: str, *, limit: int = 200) -> list[Candle] | None:
        if not self.supports_symbol(symbol) or not self.supports_timeframe(timeframe):
            return None
        try:
            raw_candles = await self.futures_rest_client.get_klines(symbol, timeframe, limit=limit)
        except BinanceRestError:
            logger.exception("failed to fetch futures candles symbol=%s timeframe=%s", symbol, timeframe)
            return None
        return [parse_rest_candle(item) for item in raw_candles]

    async def get_order_book(self, symbol: str) -> OrderBookSnapshot | None:
        if not self.supports_symbol(symbol):
            return None
        async with self._lock:
            return self.orderbook_cache.get_snapshot(symbol)

    async def get_recent_trades(self, symbol: str, *, limit: int = 100) -> list[TradePrint]:
        if not self.supports_symbol(symbol):
            return []
        async with self._lock:
            return self.trade_cache.get(symbol, limit=limit)

    async def get_price_history(self, symbol: str, *, seconds: int = 300) -> list[PricePoint]:
        if not self.supports_symbol(symbol):
            return []
        since = utc_now() - timedelta(seconds=max(seconds, 1))
        async with self._lock:
            return self.price_history_cache.get(symbol, since=since)

    async def get_funding_snapshot(self, symbol: str) -> FundingSnapshot | None:
        normalized = normalize_symbol(symbol)
        async with self._lock:
            cached = self.funding_cache.get_snapshot(normalized)
        if cached is not None and cached.fetched_at is not None:
            age_seconds = (utc_now() - cached.fetched_at).total_seconds()
            if age_seconds <= self.settings.basis_max_data_age_seconds:
                return cached
        try:
            payload = await self.futures_rest_client.get_mark_price(normalized)
        except BinanceRestError:
            logger.exception("failed to fetch funding snapshot symbol=%s", normalized)
            return cached
        snapshot = parse_funding_snapshot(payload, fetched_at=utc_now())
        async with self._lock:
            self.funding_cache.upsert_snapshot(snapshot)
        return snapshot

    async def get_funding_history(self, symbol: str, *, limit: int = 50) -> list[FundingRatePoint]:
        normalized = normalize_symbol(symbol)
        async with self._lock:
            cached = self.funding_cache.get_history(normalized, limit=limit)
        if len(cached) >= min(limit, 3):
            return cached
        try:
            payload = await self.futures_rest_client.get_funding_rate_history(normalized, limit=limit)
        except BinanceRestError:
            logger.exception("failed to fetch funding history symbol=%s", normalized)
            return cached
        history = [parse_funding_history_item(item) for item in payload]
        async with self._lock:
            self.funding_cache.seed_history(normalized, history)
        return history

    async def _bootstrap_loop(self) -> None:
        try:
            await self.seed_initial_data()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("market data bootstrap failed")

    async def _handle_ws_message(self, message: dict[str, Any]) -> None:
        stream, payload = extract_stream_payload(message)
        event_type = infer_event_type(stream, payload)
        symbol = infer_symbol(stream, payload)
        now = utc_now()
        snapshot: TickerSnapshot | None = None

        if symbol not in self.supported_symbols:
            return

        async with self._lock:
            self._set_fallback_active_locked(False)

            if event_type in {"24hrMiniTicker", "24hrTicker"}:
                last_price = parse_float(payload.get("c"))
                self.ticker_cache.upsert_ticker(
                    symbol,
                    last_price=last_price,
                    volume_24h=parse_float(payload.get("v")),
                    updated_at=now,
                    status_field="ws_status",
                    status_value="ok",
                )
                if last_price is not None and last_price > 0:
                    self.price_history_cache.upsert(PricePoint(symbol=symbol, price=last_price, timestamp=now))
                snapshot = self.ticker_cache.get(symbol)
            elif event_type == "depthUpdate":
                order_book = parse_order_book_top(symbol, payload)
                order_book_snapshot = parse_order_book_snapshot(symbol, payload)
                self.orderbook_cache.upsert(order_book)
                self.orderbook_cache.upsert_snapshot(
                    symbol,
                    bids=order_book_snapshot.bids,
                    asks=order_book_snapshot.asks,
                    updated_at=order_book_snapshot.updated_at or now,
                )
                self.ticker_cache.upsert_orderbook(
                    symbol,
                    order_book,
                    status_field="ws_status",
                    status_value="ok",
                )
                snapshot = self.ticker_cache.get(symbol)
            elif event_type == "aggTrade":
                trade_print = parse_trade_print(payload)
                self.trade_cache.upsert(trade_print)
                self.price_history_cache.upsert(
                    PricePoint(symbol=symbol, price=trade_print.price, timestamp=trade_print.trade_time)
                )
            elif event_type == "kline":
                timeframe, candle = parse_ws_candle(payload)
                if timeframe in self.supported_timeframes:
                    self.candle_cache.upsert(symbol, timeframe, candle, updated_at=now)
                    snapshot = self.ticker_cache.get(symbol)

        if snapshot is not None:
            await self._persist_snapshot_if_due(snapshot)

    async def _health_monitor_loop(self) -> None:
        while True:
            try:
                now = utc_now()
                async with self._lock:
                    fallback_active = self._should_enable_fallback(now)
                    self._set_fallback_active_locked(fallback_active)
                    self.ticker_cache.set_ws_status_all(
                        self._resolve_websocket_status(now, self.ws_client.last_message_at)
                    )

                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market data health monitor failed")
                await asyncio.sleep(1.0)

    async def _fallback_loop(self) -> None:
        while True:
            try:
                async with self._lock:
                    fallback_active = self._fallback_active

                if fallback_active:
                    for symbol in self.supported_symbols:
                        await self._refresh_symbol_from_rest(symbol, persist=True)

                    await asyncio.sleep(self.settings.market_data_rest_fallback_interval_sec)
                else:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market data fallback loop failed")
                await asyncio.sleep(self.settings.market_data_rest_fallback_interval_sec)

    async def _refresh_symbol_from_rest(self, symbol: str, *, persist: bool) -> None:
        try:
            price_payload, stats_payload, orderbook_payload = await asyncio.gather(
                self.rest_client.get_ticker_price(symbol),
                self.rest_client.get_24hr_ticker(symbol),
                self.rest_client.get_order_book(symbol, limit=self.settings.market_data_orderbook_limit),
            )
        except BinanceRestError:
            logger.exception("rest fallback update failed symbol=%s", symbol)
            async with self._lock:
                self.ticker_cache.set_rest_status(symbol, "error")
            return

        now = utc_now()
        last_price = parse_float(price_payload.get("price")) or parse_float(stats_payload.get("lastPrice"))
        volume_24h = parse_float(stats_payload.get("volume"))
        order_book = parse_order_book_top(symbol, orderbook_payload)

        async with self._lock:
            self.ticker_cache.upsert_ticker(
                symbol,
                last_price=last_price,
                volume_24h=volume_24h,
                updated_at=now,
                status_field="rest_status",
                status_value="ok",
            )
            if last_price is not None and last_price > 0:
                self.price_history_cache.upsert(PricePoint(symbol=symbol, price=last_price, timestamp=now))
            self.orderbook_cache.upsert(order_book)
            self.ticker_cache.upsert_orderbook(
                symbol,
                order_book,
                status_field="rest_status",
                status_value="ok",
            )
            self.ticker_cache.ensure(symbol).fallback_active = self._fallback_active
            snapshot = self.ticker_cache.get(symbol)

        if persist and snapshot is not None:
            await self._persist_snapshot_if_due(snapshot, force=True)

    async def _persist_snapshot_if_due(self, snapshot: TickerSnapshot, *, force: bool = False) -> None:
        if snapshot.snapshot_time is None:
            return

        now = utc_now()
        last_persisted = self._last_persisted_at.get(snapshot.symbol)
        if not force and last_persisted is not None and now - last_persisted < timedelta(seconds=5):
            return

        record = MarketSnapshot(
            symbol=snapshot.symbol,
            last_price=snapshot.last_price,
            bid_price=snapshot.bid_price,
            ask_price=snapshot.ask_price,
            best_bid_qty=snapshot.best_bid_qty,
            best_ask_qty=snapshot.best_ask_qty,
            spread_bps=snapshot.spread_bps,
            volume_24h=snapshot.volume_24h,
            ws_status=snapshot.ws_status,
            rest_status=snapshot.rest_status,
            fallback_active=snapshot.fallback_active,
            ticker_updated_at=snapshot.ticker_updated_at,
            orderbook_updated_at=snapshot.orderbook_updated_at,
            snapshot_time=snapshot.snapshot_time,
            created_at=now,
        )

        try:
            with SessionLocal() as session:
                session.add(record)
                session.commit()
        except Exception:
            logger.exception("failed to persist market snapshot symbol=%s", snapshot.symbol)
            return

        self._last_persisted_at[snapshot.symbol] = now

    def _resolve_websocket_status(self, now: datetime, last_ws_message_at: datetime | None) -> str:
        if not self._started:
            return "stopped"

        if self.ws_client.status == "stopped":
            return "stopped"

        if last_ws_message_at is None:
            return "degraded"

        elapsed_ms = (now - last_ws_message_at).total_seconds() * 1000
        if elapsed_ms > self.settings.market_data_ws_stale_ms:
            return "degraded"

        return "ok"

    def _is_fresh(self, timestamp: datetime | None, threshold_ms: int, now: datetime) -> bool:
        if timestamp is None:
            return False

        return (now - timestamp).total_seconds() * 1000 <= threshold_ms

    def _should_enable_fallback(self, now: datetime) -> bool:
        return self._resolve_websocket_status(now, self.ws_client.last_message_at) != "ok"

    def _set_fallback_active_locked(self, active: bool) -> None:
        self._fallback_active = active
        self.ticker_cache.set_fallback_active(active)

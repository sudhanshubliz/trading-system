from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import datetime

from app.market_data.types import Candle, OrderBookTop, TickerSnapshot


def _calculate_spread_bps(bid_price: float | None, ask_price: float | None) -> float | None:
    if bid_price is None or ask_price is None:
        return None

    midpoint = (bid_price + ask_price) / 2
    if midpoint <= 0:
        return None

    return ((ask_price - bid_price) / midpoint) * 10000


class CandleCache:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._store: dict[tuple[str, str], deque[Candle]] = {}
        self._updated_at: dict[tuple[str, str], datetime] = {}

    def seed(self, symbol: str, timeframe: str, candles: list[Candle], updated_at: datetime) -> None:
        key = (symbol.upper(), timeframe.lower())
        self._store[key] = deque(candles[-self._limit :], maxlen=self._limit)
        self._updated_at[key] = updated_at

    def upsert(self, symbol: str, timeframe: str, candle: Candle, updated_at: datetime) -> None:
        key = (symbol.upper(), timeframe.lower())
        if key not in self._store:
            self._store[key] = deque(maxlen=self._limit)

        bucket = self._store[key]
        if bucket and bucket[-1].open_time == candle.open_time:
            bucket[-1] = candle
        else:
            bucket.append(candle)

        self._updated_at[key] = updated_at

    def get(self, symbol: str, timeframe: str) -> list[Candle]:
        key = (symbol.upper(), timeframe.lower())
        return list(self._store.get(key, ()))

    def last_update(self, symbol: str, timeframe: str) -> datetime | None:
        key = (symbol.upper(), timeframe.lower())
        return self._updated_at.get(key)


class OrderBookCache:
    def __init__(self) -> None:
        self._store: dict[str, OrderBookTop] = {}

    def upsert(self, order_book: OrderBookTop) -> None:
        self._store[order_book.symbol.upper()] = order_book

    def get(self, symbol: str) -> OrderBookTop | None:
        value = self._store.get(symbol.upper())
        return replace(value) if value is not None else None


class TickerCache:
    def __init__(self, symbols: list[str]) -> None:
        self._store: dict[str, TickerSnapshot] = {
            symbol.upper(): TickerSnapshot(symbol=symbol.upper()) for symbol in symbols
        }

    def ensure(self, symbol: str) -> TickerSnapshot:
        normalized = symbol.upper()
        snapshot = self._store.get(normalized)
        if snapshot is None:
            snapshot = TickerSnapshot(symbol=normalized)
            self._store[normalized] = snapshot
        return snapshot

    def upsert_ticker(
        self,
        symbol: str,
        *,
        last_price: float | None,
        volume_24h: float | None,
        updated_at: datetime,
        status_field: str,
        status_value: str,
    ) -> None:
        snapshot = self.ensure(symbol)
        snapshot.last_price = last_price
        snapshot.volume_24h = volume_24h
        snapshot.ticker_updated_at = updated_at
        snapshot.snapshot_time = updated_at
        setattr(snapshot, status_field, status_value)

    def upsert_orderbook(
        self,
        symbol: str,
        order_book: OrderBookTop,
        *,
        status_field: str,
        status_value: str,
    ) -> None:
        snapshot = self.ensure(symbol)
        snapshot.bid_price = order_book.bid_price
        snapshot.ask_price = order_book.ask_price
        snapshot.best_bid_qty = order_book.best_bid_qty
        snapshot.best_ask_qty = order_book.best_ask_qty
        snapshot.orderbook_updated_at = order_book.updated_at
        snapshot.snapshot_time = order_book.updated_at
        snapshot.spread_bps = _calculate_spread_bps(order_book.bid_price, order_book.ask_price)
        setattr(snapshot, status_field, status_value)

    def set_fallback_active(self, active: bool) -> None:
        for snapshot in self._store.values():
            snapshot.fallback_active = active

    def set_ws_status_all(self, status: str) -> None:
        for snapshot in self._store.values():
            snapshot.ws_status = status

    def set_rest_status(self, symbol: str, status: str) -> None:
        self.ensure(symbol).rest_status = status

    def get(self, symbol: str) -> TickerSnapshot | None:
        value = self._store.get(symbol.upper())
        return replace(value) if value is not None else None

    def all(self) -> list[TickerSnapshot]:
        return [replace(snapshot) for snapshot in self._store.values()]

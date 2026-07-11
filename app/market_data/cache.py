from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import datetime

from app.market_data.types import Candle, FundingRatePoint, FundingSnapshot, OrderBookLevel, OrderBookSnapshot, OrderBookTop, PricePoint, TickerSnapshot, TradePrint


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
        self._snapshots: dict[str, OrderBookSnapshot] = {}
        self._update_times: dict[str, deque[datetime]] = {}

    def upsert(self, order_book: OrderBookTop) -> None:
        self._store[order_book.symbol.upper()] = order_book

    def upsert_snapshot(
        self,
        symbol: str,
        *,
        bids: list[OrderBookLevel],
        asks: list[OrderBookLevel],
        updated_at: datetime,
    ) -> None:
        normalized = symbol.upper()
        updates = self._update_times.setdefault(normalized, deque(maxlen=256))
        updates.append(updated_at)
        update_count_1s = sum(1 for item in updates if (updated_at - item).total_seconds() <= 1.0)
        update_count_5s = sum(1 for item in updates if (updated_at - item).total_seconds() <= 5.0)
        self._snapshots[normalized] = OrderBookSnapshot(
            symbol=normalized,
            bids=list(bids),
            asks=list(asks),
            updated_at=updated_at,
            update_count_1s=update_count_1s,
            update_count_5s=update_count_5s,
        )

    def get(self, symbol: str) -> OrderBookTop | None:
        value = self._store.get(symbol.upper())
        return replace(value) if value is not None else None

    def get_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        snapshot = self._snapshots.get(symbol.upper())
        if snapshot is None:
            return None
        return OrderBookSnapshot(
            symbol=snapshot.symbol,
            bids=list(snapshot.bids),
            asks=list(snapshot.asks),
            updated_at=snapshot.updated_at,
            update_count_1s=snapshot.update_count_1s,
            update_count_5s=snapshot.update_count_5s,
        )


class TradePrintCache:
    def __init__(self, limit: int = 200) -> None:
        self._limit = limit
        self._store: dict[str, deque[TradePrint]] = {}

    def upsert(self, trade: TradePrint) -> None:
        symbol = trade.symbol.upper()
        if symbol not in self._store:
            self._store[symbol] = deque(maxlen=self._limit)
        self._store[symbol].append(trade)

    def get(self, symbol: str, *, limit: int | None = None) -> list[TradePrint]:
        items = list(self._store.get(symbol.upper(), ()))
        if limit is not None:
            items = items[-max(limit, 0) :]
        return [replace(item) for item in items]


class PriceHistoryCache:
    def __init__(self, limit: int = 600, minimum_interval_ms: int = 250) -> None:
        self._limit = max(limit, 2)
        self._minimum_interval_ms = max(minimum_interval_ms, 0)
        self._store: dict[str, deque[PricePoint]] = {}

    def upsert(self, point: PricePoint) -> None:
        symbol = point.symbol.upper()
        bucket = self._store.setdefault(symbol, deque(maxlen=self._limit))
        if bucket:
            elapsed_ms = (point.timestamp - bucket[-1].timestamp).total_seconds() * 1000.0
            if elapsed_ms < self._minimum_interval_ms:
                bucket[-1] = point
                return
        bucket.append(point)

    def get(self, symbol: str, *, since: datetime | None = None) -> list[PricePoint]:
        items = list(self._store.get(symbol.upper(), ()))
        if since is not None:
            items = [item for item in items if item.timestamp >= since]
        return items


class FundingCache:
    def __init__(self, history_limit: int = 128) -> None:
        self._history_limit = history_limit
        self._snapshots: dict[str, FundingSnapshot] = {}
        self._history: dict[str, deque[FundingRatePoint]] = {}

    def upsert_snapshot(self, snapshot: FundingSnapshot) -> None:
        self._snapshots[snapshot.symbol.upper()] = snapshot

    def get_snapshot(self, symbol: str) -> FundingSnapshot | None:
        value = self._snapshots.get(symbol.upper())
        if value is None:
            return None
        return replace(value)

    def seed_history(self, symbol: str, history: list[FundingRatePoint]) -> None:
        self._history[symbol.upper()] = deque(history[-self._history_limit :], maxlen=self._history_limit)

    def get_history(self, symbol: str, *, limit: int | None = None) -> list[FundingRatePoint]:
        items = list(self._history.get(symbol.upper(), ()))
        if limit is not None:
            items = items[-max(limit, 0) :]
        return [replace(item) for item in items]


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

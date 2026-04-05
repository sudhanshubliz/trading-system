from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Candle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


@dataclass(slots=True)
class OrderBookTop:
    symbol: str
    bid_price: float | None
    ask_price: float | None
    best_bid_qty: float | None
    best_ask_qty: float | None
    updated_at: datetime


@dataclass(slots=True)
class TickerSnapshot:
    symbol: str
    last_price: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    best_bid_qty: float | None = None
    best_ask_qty: float | None = None
    spread_bps: float | None = None
    volume_24h: float | None = None
    ws_status: str = "degraded"
    rest_status: str = "unknown"
    fallback_active: bool = False
    ticker_updated_at: datetime | None = None
    orderbook_updated_at: datetime | None = None
    snapshot_time: datetime | None = None


@dataclass(slots=True)
class SymbolHealth:
    symbol: str
    ticker_fresh: bool
    orderbook_fresh: bool
    candles_fresh: dict[str, bool] = field(default_factory=dict)
    last_price: float | None = None
    ticker_updated_at: datetime | None = None
    orderbook_updated_at: datetime | None = None


@dataclass(slots=True)
class MarketDataHealth:
    status: str
    websocket_status: str
    fallback_active: bool
    supported_symbols: list[str]
    supported_timeframes: list[str]
    last_ws_message_at: datetime | None
    symbols: dict[str, SymbolHealth]
    timestamp: datetime

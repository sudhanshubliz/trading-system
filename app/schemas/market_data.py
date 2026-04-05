from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CandleResponse(BaseModel):
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


class CandleSeriesResponse(BaseModel):
    symbol: str
    timeframe: str
    items: list[CandleResponse]


class MarketSnapshotResponse(BaseModel):
    symbol: str
    last_price: float | None
    bid_price: float | None
    ask_price: float | None
    best_bid_qty: float | None
    best_ask_qty: float | None
    spread_bps: float | None
    volume_24h: float | None
    ws_status: str
    rest_status: str
    fallback_active: bool
    ticker_updated_at: datetime | None
    orderbook_updated_at: datetime | None
    snapshot_time: datetime | None


class MarketSnapshotListResponse(BaseModel):
    items: list[MarketSnapshotResponse]


class SymbolHealthResponse(BaseModel):
    symbol: str
    ticker_fresh: bool
    orderbook_fresh: bool
    candles_fresh: dict[str, bool]
    last_price: float | None
    ticker_updated_at: datetime | None
    orderbook_updated_at: datetime | None


class MarketDataHealthResponse(BaseModel):
    status: str
    websocket_status: str
    fallback_active: bool
    supported_symbols: list[str]
    supported_timeframes: list[str]
    last_ws_message_at: datetime | None
    symbols: dict[str, SymbolHealthResponse]
    timestamp: datetime

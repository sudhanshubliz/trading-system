from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.market_data.types import Candle, OrderBookTop


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ms_to_utc(value: int | str | float) -> datetime:
    return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def normalize_symbol(value: str) -> str:
    return value.upper()


def normalize_timeframe(value: str) -> str:
    return value.lower()


def extract_stream_payload(message: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    stream = message.get("stream")
    data = message.get("data")
    if isinstance(stream, str) and isinstance(data, dict):
        return stream, data
    return "", message


def infer_event_type(stream: str, payload: dict[str, Any]) -> str:
    event_type = str(payload.get("e", "")).strip()
    if event_type:
        return event_type

    stream_name = stream.lower()
    if "@depth" in stream_name:
        return "depthUpdate"
    if "@kline_" in stream_name:
        return "kline"
    if "@miniticker" in stream_name:
        return "24hrMiniTicker"
    if "@ticker" in stream_name:
        return "24hrTicker"

    return ""


def infer_symbol(stream: str, payload: dict[str, Any]) -> str:
    payload_symbol = payload.get("s")
    if isinstance(payload_symbol, str) and payload_symbol:
        return normalize_symbol(payload_symbol)

    if "@" in stream:
        return normalize_symbol(stream.split("@", maxsplit=1)[0])

    return ""


def parse_rest_candle(raw: list[Any]) -> Candle:
    return Candle(
        open_time=ms_to_utc(raw[0]),
        open=float(raw[1]),
        high=float(raw[2]),
        low=float(raw[3]),
        close=float(raw[4]),
        volume=float(raw[5]),
        is_closed=True,
    )


def parse_order_book_top(symbol: str, payload: dict[str, Any]) -> OrderBookTop:
    bids = payload.get("bids") or payload.get("b") or []
    asks = payload.get("asks") or payload.get("a") or []

    best_bid = bids[0] if bids else [None, None]
    best_ask = asks[0] if asks else [None, None]

    return OrderBookTop(
        symbol=normalize_symbol(symbol),
        bid_price=parse_float(best_bid[0]),
        ask_price=parse_float(best_ask[0]),
        best_bid_qty=parse_float(best_bid[1]),
        best_ask_qty=parse_float(best_ask[1]),
        updated_at=utc_now(),
    )


def parse_ws_candle(payload: dict[str, Any]) -> tuple[str, Candle]:
    kline = payload["k"]
    timeframe = normalize_timeframe(str(kline["i"]))
    candle = Candle(
        open_time=ms_to_utc(kline["t"]),
        open=float(kline["o"]),
        high=float(kline["h"]),
        low=float(kline["l"]),
        close=float(kline["c"]),
        volume=float(kline["v"]),
        is_closed=bool(kline["x"]),
    )
    return timeframe, candle

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.market_data.types import Candle, FundingRatePoint, FundingSnapshot, OrderBookLevel, OrderBookSnapshot, OrderBookTop, TradePrint


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
    if "@aggtrade" in stream_name:
        return "aggTrade"
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
    snapshot = parse_order_book_snapshot(symbol, payload)
    best_bid = snapshot.bids[0] if snapshot.bids else OrderBookLevel(price=0.0, quantity=0.0)
    best_ask = snapshot.asks[0] if snapshot.asks else OrderBookLevel(price=0.0, quantity=0.0)
    return OrderBookTop(
        symbol=normalize_symbol(symbol),
        bid_price=best_bid.price if snapshot.bids else None,
        ask_price=best_ask.price if snapshot.asks else None,
        best_bid_qty=best_bid.quantity if snapshot.bids else None,
        best_ask_qty=best_ask.quantity if snapshot.asks else None,
        updated_at=snapshot.updated_at or utc_now(),
    )


def parse_order_book_snapshot(symbol: str, payload: dict[str, Any]) -> OrderBookSnapshot:
    bids = payload.get("bids") or payload.get("b") or []
    asks = payload.get("asks") or payload.get("a") or []
    return OrderBookSnapshot(
        symbol=normalize_symbol(symbol),
        bids=[
            OrderBookLevel(price=float(level[0]), quantity=float(level[1]))
            for level in bids
            if len(level) >= 2 and parse_float(level[0]) is not None and parse_float(level[1]) is not None
        ],
        asks=[
            OrderBookLevel(price=float(level[0]), quantity=float(level[1]))
            for level in asks
            if len(level) >= 2 and parse_float(level[0]) is not None and parse_float(level[1]) is not None
        ],
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


def parse_trade_print(payload: dict[str, Any]) -> TradePrint:
    return TradePrint(
        symbol=normalize_symbol(str(payload["s"])),
        price=float(payload["p"]),
        quantity=float(payload["q"]),
        is_buyer_maker=bool(payload["m"]),
        trade_time=ms_to_utc(payload["T"]),
    )


def parse_funding_snapshot(payload: dict[str, Any], *, fetched_at: datetime | None = None) -> FundingSnapshot:
    return FundingSnapshot(
        symbol=normalize_symbol(str(payload["symbol"])),
        mark_price=parse_float(payload.get("markPrice")),
        index_price=parse_float(payload.get("indexPrice")),
        last_funding_rate=parse_float(payload.get("lastFundingRate")),
        next_funding_time=ms_to_utc(payload["nextFundingTime"]) if payload.get("nextFundingTime") is not None else None,
        fetched_at=fetched_at or utc_now(),
    )


def parse_funding_history_item(payload: dict[str, Any]) -> FundingRatePoint:
    return FundingRatePoint(
        symbol=normalize_symbol(str(payload["symbol"])),
        funding_rate=float(payload["fundingRate"]),
        funding_time=ms_to_utc(payload["fundingTime"]),
        mark_price=parse_float(payload.get("markPrice")),
    )

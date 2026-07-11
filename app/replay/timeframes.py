from __future__ import annotations

from datetime import datetime, timedelta


def timeframe_duration(timeframe: str) -> timedelta:
    """Return the deterministic duration for a Binance-style candle interval."""

    value = timeframe.strip()
    if len(value) < 2:
        raise ValueError(f"unsupported timeframe: {timeframe}")

    unit = value[-1]
    try:
        count = int(value[:-1])
    except ValueError as exc:
        raise ValueError(f"unsupported timeframe: {timeframe}") from exc
    if count <= 0:
        raise ValueError(f"unsupported timeframe: {timeframe}")

    if unit == "s":
        return timedelta(seconds=count)
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    if unit == "d":
        return timedelta(days=count)
    if unit == "w":
        return timedelta(weeks=count)
    if unit == "M":
        # Binance monthly candles are calendar based. Thirty days is an explicit
        # best-effort fallback until replay candles carry a venue close timestamp.
        return timedelta(days=30 * count)
    raise ValueError(f"unsupported timeframe: {timeframe}")


def candle_close_time(open_time: datetime, timeframe: str) -> datetime:
    return open_time + timeframe_duration(timeframe)

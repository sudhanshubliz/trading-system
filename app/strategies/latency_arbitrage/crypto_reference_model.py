from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.market_data.types import Candle, PricePoint, TickerSnapshot


@dataclass(slots=True)
class ReferenceState:
    symbol: str
    current_price: float
    return_30s_pct: float
    return_1m_pct: float
    return_5m_pct: float
    realized_volatility_pct: float
    reference_fidelity: str = "candle_approximation"
    latest_timestamp: datetime | None = None
    price_point_count: int = 0


def build_reference_state(symbol: str, candles_5m: list[Candle]) -> ReferenceState | None:
    if not candles_5m:
        return None
    latest = candles_5m[-1]
    previous = candles_5m[-2] if len(candles_5m) >= 2 else latest
    return_5m_pct = ((latest.close - previous.close) / max(previous.close, 1e-9)) * 100.0
    # Replay/live caches are 5m candles here, so shorter windows are conservative approximations of intra-bar drift.
    return_1m_pct = return_5m_pct * 0.35
    return_30s_pct = return_5m_pct * 0.2
    sample = candles_5m[-20:]
    if len(sample) >= 2:
        returns = [((sample[index].close - sample[index - 1].close) / max(sample[index - 1].close, 1e-9)) for index in range(1, len(sample))]
        realized_volatility_pct = math.sqrt(sum(value * value for value in returns) / len(returns)) * 100.0
    else:
        realized_volatility_pct = abs(return_5m_pct)
    return ReferenceState(
        symbol=symbol.upper(),
        current_price=latest.close,
        return_30s_pct=round(return_30s_pct, 6),
        return_1m_pct=round(return_1m_pct, 6),
        return_5m_pct=round(return_5m_pct, 6),
        realized_volatility_pct=round(realized_volatility_pct, 6),
        reference_fidelity="candle_approximation",
        latest_timestamp=latest.open_time,
        price_point_count=0,
    )


def build_realtime_reference_state(
    symbol: str,
    *,
    snapshot: TickerSnapshot | None,
    price_history: list[PricePoint],
    candles_5m: list[Candle],
    now: datetime | None = None,
    max_age_seconds: int = 10,
) -> ReferenceState | None:
    observed_at = now or datetime.now(timezone.utc)
    if snapshot is None or snapshot.last_price is None or snapshot.last_price <= 0:
        return None
    updated_at = snapshot.ticker_updated_at or snapshot.snapshot_time
    if updated_at is None or (observed_at - updated_at).total_seconds() > max(max_age_seconds, 1):
        return None

    points = sorted(
        [
            item
            for item in price_history
            if item.symbol.upper() == symbol.upper()
            and item.price > 0
            and item.timestamp <= observed_at
        ],
        key=lambda item: item.timestamp,
    )
    return_30s = _window_return(points, snapshot.last_price, observed_at, seconds=30)
    return_1m = _window_return(points, snapshot.last_price, observed_at, seconds=60)
    return_5m = _window_return(points, snapshot.last_price, observed_at, seconds=300)
    candle_state = build_reference_state(symbol, candles_5m)
    if return_5m is None and candle_state is not None:
        return_5m = candle_state.return_5m_pct
    if return_30s is None or return_1m is None:
        if candle_state is None:
            return None
        return ReferenceState(
            symbol=symbol.upper(),
            current_price=snapshot.last_price,
            return_30s_pct=candle_state.return_30s_pct,
            return_1m_pct=candle_state.return_1m_pct,
            return_5m_pct=return_5m if return_5m is not None else candle_state.return_5m_pct,
            realized_volatility_pct=candle_state.realized_volatility_pct,
            reference_fidelity="candle_approximation",
            latest_timestamp=updated_at,
            price_point_count=len(points),
        )

    returns = [
        (points[index].price - points[index - 1].price) / max(points[index - 1].price, 1e-9)
        for index in range(1, len(points))
        if points[index].timestamp > points[index - 1].timestamp
    ]
    realized_volatility_pct = (
        math.sqrt(sum(value * value for value in returns) / len(returns)) * 100.0
        if returns
        else abs(return_1m)
    )
    return ReferenceState(
        symbol=symbol.upper(),
        current_price=snapshot.last_price,
        return_30s_pct=round(return_30s, 6),
        return_1m_pct=round(return_1m, 6),
        return_5m_pct=round(return_5m or 0.0, 6),
        realized_volatility_pct=round(realized_volatility_pct, 6),
        reference_fidelity="realtime_price_history",
        latest_timestamp=updated_at,
        price_point_count=len(points),
    )


def _window_return(
    points: list[PricePoint],
    current_price: float,
    now: datetime,
    *,
    seconds: int,
) -> float | None:
    cutoff = now.timestamp() - seconds
    eligible = [item for item in points if item.timestamp.timestamp() <= cutoff]
    if not eligible:
        return None
    anchor = eligible[-1]
    if cutoff - anchor.timestamp.timestamp() > max(seconds * 0.25, 3.0):
        return None
    return ((current_price - anchor.price) / max(anchor.price, 1e-9)) * 100.0

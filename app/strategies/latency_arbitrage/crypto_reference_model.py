from __future__ import annotations

import math
from dataclasses import dataclass

from app.market_data.types import Candle


@dataclass(slots=True)
class ReferenceState:
    symbol: str
    current_price: float
    return_30s_pct: float
    return_1m_pct: float
    return_5m_pct: float
    realized_volatility_pct: float


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
    )

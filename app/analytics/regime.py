from __future__ import annotations

from app.analytics.metrics import stddev, trade_win_rate, zero_safe_divide
from app.execution.types import Trade
from app.persistence.db import safe_float

VALID_REGIMES = ("trending", "ranging", "high-vol", "low-vol")


def classify_regime(
    trades: list[Trade],
    *,
    volatility_lookback: int,
    trend_lookback: int,
) -> str:
    closed = [trade for trade in trades if trade.closed_at is not None]
    if not closed:
        return "ranging"
    recent = closed[-max(volatility_lookback, trend_lookback, 1) :]
    pnl_values = [safe_float(trade.realized_pnl) for trade in recent]
    volatility = stddev(pnl_values)
    avg_abs_pnl = safe_float(sum(abs(value) for value in pnl_values) / len(pnl_values))
    win_rate = trade_win_rate(recent)
    directional_ratio = zero_safe_divide(abs(sum(pnl_values)), max(sum(abs(value) for value in pnl_values), 1.0))

    if volatility >= max(avg_abs_pnl * 1.1, 25.0):
        return "high-vol"
    if volatility <= max(avg_abs_pnl * 0.35, 10.0):
        return "low-vol"
    if win_rate >= 55.0 and directional_ratio >= 0.45:
        return "trending"
    return "ranging"

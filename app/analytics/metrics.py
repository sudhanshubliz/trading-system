from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

from app.execution.types import Trade
from app.persistence.db import safe_float


def zero_safe_divide(numerator: float, denominator: float) -> float:
    numerator_value = safe_float(numerator)
    denominator_value = safe_float(denominator)
    if denominator_value == 0:
        return 0.0
    return safe_float(numerator_value / denominator_value)


def trade_holding_minutes(trade: Trade) -> float:
    if trade.closed_at is None:
        return 0.0
    duration = trade.closed_at - trade.opened_at
    return safe_float(max(duration.total_seconds() / 60.0, 0.0))


def trade_win_rate(trades: list[Trade]) -> float:
    closed = [trade for trade in trades if trade.closed_at is not None]
    if not closed:
        return 0.0
    wins = sum(1 for trade in closed if safe_float(trade.realized_pnl) > 0)
    return safe_float((wins / len(closed)) * 100.0)


def expectancy(trades: list[Trade]) -> float:
    closed = [trade for trade in trades if trade.closed_at is not None]
    if not closed:
        return 0.0
    pnl_total = safe_float(sum(safe_float(trade.realized_pnl) for trade in closed))
    return safe_float(pnl_total / len(closed))


def max_drawdown_pct(trades: list[Trade], *, starting_balance: float) -> float:
    equity = max(safe_float(starting_balance), 1.0)
    peak = equity
    max_drawdown = 0.0
    ordered = sorted(
        [trade for trade in trades if trade.closed_at is not None],
        key=lambda item: item.closed_at or item.updated_at,
    )
    for trade in ordered:
        equity = safe_float(equity + safe_float(trade.realized_pnl))
        peak = max(peak, equity)
        drawdown = safe_float(((peak - equity) / peak) * 100.0) if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
    return safe_float(max_drawdown)


def capital_efficiency(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    deployed = safe_float(sum(safe_float(trade.requested_entry_price * trade.quantity) for trade in trades))
    pnl_total = safe_float(sum(safe_float(trade.realized_pnl) for trade in trades))
    return zero_safe_divide(pnl_total, deployed)


def average_holding_minutes(trades: list[Trade]) -> float:
    values = [trade_holding_minutes(trade) for trade in trades if trade.closed_at is not None]
    if not values:
        return 0.0
    return safe_float(sum(values) / len(values))


def execution_mode_split(trades: list[Trade]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for trade in trades:
        counts[trade.execution_mode] += 1
    return dict(sorted(counts.items()))


def stddev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return safe_float(math.sqrt(max(variance, 0.0)))

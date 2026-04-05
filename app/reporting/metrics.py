from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def safe_number(value: float | int) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        return 0.0
    return round(numeric, 4)


def win_rate(pnls: list[float]) -> float:
    if not pnls:
        return 0.0
    return safe_number((sum(1 for pnl in pnls if pnl > 0) / len(pnls)) * 100.0)


def expectancy(pnls: list[float]) -> float:
    if not pnls:
        return 0.0
    return safe_number(sum(pnls) / len(pnls))


def profit_factor(pnls: list[float]) -> float:
    gross_profit = sum(max(pnl, 0.0) for pnl in pnls)
    gross_loss = sum(abs(min(pnl, 0.0)) for pnl in pnls)
    if gross_loss == 0:
        return 999.0 if gross_profit > 0 else 0.0
    return safe_number(gross_profit / gross_loss)


def max_drawdown(equity_curve: list[dict[str, Any]]) -> float:
    if not equity_curve:
        return 0.0
    peak = float(equity_curve[0].get("equity", 0.0))
    worst = 0.0
    for point in equity_curve:
        equity = float(point.get("equity", 0.0))
        peak = max(peak, equity)
        if peak <= 0:
            continue
        drawdown = ((peak - equity) / peak) * 100.0
        worst = max(worst, drawdown)
    return safe_number(worst)


def average_hold_minutes(trades: list[dict[str, Any]]) -> float:
    values: list[float] = []
    for trade in trades:
        opened_at = trade.get("opened_at")
        closed_at = trade.get("closed_at")
        if not isinstance(opened_at, datetime) or not isinstance(closed_at, datetime):
            continue
        values.append(max((closed_at - opened_at).total_seconds() / 60.0, 0.0))
    if not values:
        return 0.0
    return safe_number(sum(values) / len(values))


def average_risk_per_trade(trades: list[dict[str, Any]]) -> float:
    values: list[float] = []
    for trade in trades:
        execution_price = float(trade.get("execution_price", 0.0) or 0.0)
        stop_loss = float(trade.get("stop_loss", 0.0) or 0.0)
        quantity = float(trade.get("quantity", 0.0) or 0.0)
        if execution_price <= 0 or quantity <= 0:
            continue
        values.append(abs(execution_price - stop_loss) * quantity)
    if not values:
        return 0.0
    return safe_number(sum(values) / len(values))


def build_equity_curve(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    equity = 0.0
    curve: list[dict[str, Any]] = []
    ordered = sorted(
        [trade for trade in trades if isinstance(trade.get("closed_at"), datetime)],
        key=lambda item: item["closed_at"],
    )
    for trade in ordered:
        equity += float(trade.get("realized_pnl", 0.0) or 0.0)
        curve.append(
            {
                "timestamp": trade["closed_at"],
                "equity": safe_number(equity),
            }
        )
    return curve


def build_drawdown_timeline(equity_curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peak = 0.0
    timeline: list[dict[str, Any]] = []
    for point in equity_curve:
        equity = float(point.get("equity", 0.0) or 0.0)
        peak = max(peak, equity)
        drawdown_pct = 0.0 if peak <= 0 else ((peak - equity) / peak) * 100.0
        timeline.append(
            {
                "timestamp": point.get("timestamp"),
                "equity": safe_number(equity),
                "drawdown_pct": safe_number(drawdown_pct),
            }
        )
    return timeline

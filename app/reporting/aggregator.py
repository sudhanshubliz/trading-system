from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.persistence.repositories.trades_repo import TradesRepository
from app.reporting.metrics import (
    average_hold_minutes,
    average_risk_per_trade,
    build_drawdown_timeline,
    build_equity_curve,
    expectancy,
    max_drawdown,
    profit_factor,
    safe_number,
    win_rate,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReportAggregator:
    def __init__(self, trades_repo: TradesRepository) -> None:
        self.trades_repo = trades_repo

    def build_scope_report(self, scope: str, execution_mode: str | None = None) -> dict[str, Any]:
        trades = [
            trade
            for trade in self.trades_repo.list_trades(execution_mode)
            if trade.closed_at is not None
        ]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for trade in trades:
            closed_at = trade.closed_at or trade.updated_at
            if closed_at is None:
                continue
            if scope == "daily":
                key = closed_at.astimezone(timezone.utc).date().isoformat()
            elif scope == "weekly":
                iso_year, iso_week, _ = closed_at.isocalendar()
                key = f"{iso_year}-W{iso_week:02d}"
            elif scope == "strategy":
                key = trade.strategy_name
            elif scope == "symbol":
                key = trade.symbol
            else:
                key = "all"
            grouped[key].append(asdict(trade))

        items = [self._build_item(label, entries) for label, entries in sorted(grouped.items())]
        return {
            "scope": scope,
            "execution_mode": execution_mode or "all",
            "generated_at": utc_now(),
            "count": len(items),
            "items": items,
        }

    def _build_item(self, label: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        pnls = [float(item.get("realized_pnl", 0.0) or 0.0) for item in entries]
        equity_curve = build_equity_curve(entries)
        return {
            "group": label,
            "total_trades": len(entries),
            "win_rate": win_rate(pnls),
            "net_pnl": safe_number(sum(pnls)),
            "expectancy": expectancy(pnls),
            "profit_factor": profit_factor(pnls),
            "max_drawdown": max_drawdown(equity_curve),
            "average_hold_minutes": average_hold_minutes(entries),
            "risk_per_trade": average_risk_per_trade(entries),
            "equity_curve": equity_curve,
            "drawdown_timeline": build_drawdown_timeline(equity_curve),
        }

from __future__ import annotations

from datetime import datetime, timezone

from app.execution.types import PnlSummary, Position, Trade


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_pnl_summary(positions: list[Position], trades: list[Trade]) -> PnlSummary:
    now = utc_now()
    realized_pnl_total = sum(position.realized_pnl for position in positions)
    unrealized_pnl_total = sum(
        position.unrealized_pnl for position in positions if position.status != "closed"
    )
    daily_pnl = sum(
        position.realized_pnl
        for position in positions
        if (
            (position.closed_at is not None and position.closed_at.date() == now.date())
            or (position.updated_at.date() == now.date() and position.realized_pnl != 0)
        )
    )
    open_positions = sum(1 for position in positions if position.status != "closed")
    closed_positions = sum(1 for position in positions if position.status == "closed")
    return PnlSummary(
        realized_pnl_total=realized_pnl_total,
        unrealized_pnl_total=unrealized_pnl_total,
        daily_pnl=daily_pnl,
        open_positions=open_positions,
        closed_positions=closed_positions,
        total_trades=len(trades),
        timestamp=now,
        gross_realized_pnl_total=sum(position.gross_realized_pnl for position in positions),
        fees_paid_total=sum(position.fees_paid for position in positions),
        slippage_cost_total=sum(position.slippage_cost for position in positions),
    )

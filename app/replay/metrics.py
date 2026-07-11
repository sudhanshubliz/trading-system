from __future__ import annotations

from app.replay.types import EquityPoint, ReplayMetrics, ReplayTradeResult


def calculate_win_rate(trades: list[ReplayTradeResult]) -> float:
    if not trades:
        return 0.0
    winning = sum(1 for trade in trades if trade.realized_pnl > 0)
    return round((winning / len(trades)) * 100, 2)


def calculate_profit_factor(trades: list[ReplayTradeResult]) -> float:
    gross_profit = sum(max(trade.realized_pnl, 0.0) for trade in trades)
    gross_loss = sum(abs(min(trade.realized_pnl, 0.0)) for trade in trades)
    if gross_loss == 0:
        return 999.0 if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 4)


def calculate_expectancy(trades: list[ReplayTradeResult]) -> float:
    if not trades:
        return 0.0
    return round(sum(trade.realized_pnl for trade in trades) / len(trades), 4)


def calculate_drawdown(equity_curve: list[EquityPoint]) -> tuple[float, float]:
    if not equity_curve:
        return 0.0, 0.0

    peak = equity_curve[0].equity
    max_drawdown_abs = 0.0
    max_drawdown_pct = 0.0
    for point in equity_curve:
        if point.equity > peak:
            peak = point.equity
        drawdown_abs = max(peak - point.equity, 0.0)
        drawdown_pct = (drawdown_abs / peak * 100) if peak > 0 else 0.0
        max_drawdown_abs = max(max_drawdown_abs, drawdown_abs)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
    return round(max_drawdown_abs, 4), round(max_drawdown_pct, 4)


def build_replay_metrics(
    *,
    initial_balance: float,
    trades: list[ReplayTradeResult],
    equity_curve: list[EquityPoint],
) -> ReplayMetrics:
    winning_trades = sum(1 for trade in trades if trade.realized_pnl > 0)
    losing_trades = sum(1 for trade in trades if trade.realized_pnl < 0)
    realized_pnl_total = round(sum(trade.realized_pnl for trade in trades), 4)
    gross_realized_pnl_total = round(sum(trade.gross_realized_pnl for trade in trades), 4)
    fees_paid_total = round(sum(trade.fees_paid for trade in trades), 4)
    slippage_cost_total = round(sum(trade.slippage_cost for trade in trades), 4)
    turnover_notional = round(
        sum((abs(trade.entry_price) + abs(trade.exit_price)) * trade.quantity for trade in trades),
        4,
    )
    unrealized_pnl_final = round(equity_curve[-1].unrealized_pnl, 4) if equity_curve else 0.0
    ending_balance = round(initial_balance + realized_pnl_total + unrealized_pnl_final, 4)
    max_drawdown_abs, max_drawdown_pct = calculate_drawdown(equity_curve)
    return ReplayMetrics(
        total_trades=len(trades),
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=calculate_win_rate(trades),
        profit_factor=calculate_profit_factor(trades),
        expectancy=calculate_expectancy(trades),
        max_drawdown_abs=max_drawdown_abs,
        max_drawdown_pct=max_drawdown_pct,
        realized_pnl_total=realized_pnl_total,
        unrealized_pnl_final=unrealized_pnl_final,
        ending_balance=ending_balance,
        equity_curve=equity_curve,
        gross_realized_pnl_total=gross_realized_pnl_total,
        fees_paid_total=fees_paid_total,
        slippage_cost_total=slippage_cost_total,
        turnover_notional=turnover_notional,
    )

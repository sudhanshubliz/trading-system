from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.replay.types import ReplayRun, ReplayTradeResult, WalkForwardFoldMetrics, WalkForwardReplayReport


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_walk_forward_report(
    run: ReplayRun,
    *,
    start_time: datetime,
    end_time: datetime,
    fold_count: int,
    minimum_days: int,
    minimum_trades: int,
    minimum_profit_factor: float,
    maximum_drawdown_pct: float,
) -> WalkForwardReplayReport:
    resolved_fold_count = max(fold_count, 1)
    evidence_seconds = max((end_time - start_time).total_seconds(), 0.0)
    evidence_days = evidence_seconds / 86400.0
    fold_seconds = evidence_seconds / resolved_fold_count if resolved_fold_count else 0.0
    folds: list[WalkForwardFoldMetrics] = []

    for index in range(resolved_fold_count):
        fold_start = start_time + timedelta(seconds=fold_seconds * index)
        fold_end = end_time if index == resolved_fold_count - 1 else start_time + timedelta(seconds=fold_seconds * (index + 1))
        trades = [
            trade
            for trade in run.trades
            if trade.closed_at is not None
            and fold_start <= trade.closed_at
            and (trade.closed_at <= fold_end if index == resolved_fold_count - 1 else trade.closed_at < fold_end)
        ]
        metrics = _trade_metrics(trades, initial_balance=run.initial_balance)
        blockers: list[str] = []
        if not trades:
            blockers.append("fold_has_no_trades")
        if metrics["expectancy"] <= 0:
            blockers.append("fold_expectancy_not_positive")
        if metrics["profit_factor"] < 1.0:
            blockers.append("fold_profit_factor_below_one")
        folds.append(
            WalkForwardFoldMetrics(
                fold_index=index + 1,
                start_time=fold_start,
                end_time=fold_end,
                total_trades=len(trades),
                net_pnl=metrics["net_pnl"],
                expectancy=metrics["expectancy"],
                profit_factor=metrics["profit_factor"],
                max_drawdown_pct=metrics["max_drawdown_pct"],
                fees_paid=metrics["fees_paid"],
                slippage_cost=metrics["slippage_cost"],
                turnover_notional=metrics["turnover_notional"],
                passed=not blockers,
                blockers=blockers,
            )
        )

    metrics = run.metrics
    total_trades = metrics.total_trades if metrics is not None else len(run.trades)
    net_pnl = metrics.realized_pnl_total if metrics is not None else round(sum(item.realized_pnl for item in run.trades), 4)
    fallback_metrics = _trade_metrics(run.trades, initial_balance=run.initial_balance)
    expectancy = metrics.expectancy if metrics is not None else fallback_metrics["expectancy"]
    profit_factor = metrics.profit_factor if metrics is not None else fallback_metrics["profit_factor"]
    max_drawdown_pct = metrics.max_drawdown_pct if metrics is not None else fallback_metrics["max_drawdown_pct"]
    fees_paid = metrics.fees_paid_total if metrics is not None else round(sum(item.fees_paid for item in run.trades), 4)
    slippage_cost = metrics.slippage_cost_total if metrics is not None else round(sum(item.slippage_cost for item in run.trades), 4)
    turnover_notional = metrics.turnover_notional if metrics is not None else fallback_metrics["turnover_notional"]
    positive_folds = sum(item.net_pnl > 0 and item.expectancy > 0 for item in folds)
    required_positive_folds = max(1, math.ceil(resolved_fold_count * 2 / 3))

    blockers: list[str] = []
    if evidence_days < minimum_days:
        blockers.append("minimum_evidence_days_not_met")
    if total_trades < minimum_trades:
        blockers.append("minimum_trades_not_met")
    if expectancy <= 0:
        blockers.append("full_period_expectancy_not_positive")
    if profit_factor < minimum_profit_factor:
        blockers.append("full_period_profit_factor_below_minimum")
    if max_drawdown_pct > maximum_drawdown_pct:
        blockers.append("full_period_drawdown_exceeded")
    if positive_folds < required_positive_folds:
        blockers.append("walk_forward_positive_folds_below_minimum")

    return WalkForwardReplayReport(
        run_id=run.run_id,
        start_time=start_time,
        end_time=end_time,
        evidence_days=round(evidence_days, 4),
        fold_count=resolved_fold_count,
        positive_fold_count=positive_folds,
        required_positive_folds=required_positive_folds,
        total_trades=total_trades,
        net_pnl=round(net_pnl, 4),
        expectancy=round(expectancy, 4),
        profit_factor=round(profit_factor, 4),
        max_drawdown_pct=round(max_drawdown_pct, 4),
        fees_paid=round(fees_paid, 4),
        slippage_cost=round(slippage_cost, 4),
        turnover_notional=round(turnover_notional, 4),
        passed=not blockers,
        blockers=blockers,
        folds=folds,
        notes=[
            "Folds are chronological and use only trades closed inside each forward window.",
            "No parameter selection is performed between folds; this evaluates the fixed configured strategy without lookahead.",
            "P&L is net of native simulated fees and exit slippage.",
        ],
        generated_at=utc_now(),
    )


def _trade_metrics(trades: list[ReplayTradeResult], *, initial_balance: float) -> dict[str, float]:
    ordered = sorted(trades, key=lambda item: item.closed_at or item.opened_at)
    values = [item.realized_pnl for item in ordered]
    gross_profit = sum(max(value, 0.0) for value in values)
    gross_loss = sum(abs(min(value, 0.0)) for value in values)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    capital_base = max(initial_balance, 1.0)
    return {
        "net_pnl": round(sum(values), 4),
        "expectancy": round(sum(values) / len(values), 4) if values else 0.0,
        "profit_factor": round(profit_factor, 4),
        "max_drawdown_pct": round(max_drawdown / capital_base * 100.0, 4),
        "fees_paid": round(sum(item.fees_paid for item in ordered), 4),
        "slippage_cost": round(sum(item.slippage_cost for item in ordered), 4),
        "turnover_notional": round(
            sum((abs(item.entry_price) + abs(item.exit_price)) * item.quantity for item in ordered),
            4,
        ),
    }

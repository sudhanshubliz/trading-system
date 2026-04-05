from __future__ import annotations

import math
from datetime import datetime, timezone

from app.config.settings import Settings
from app.execution.types import Position, Trade
from app.live.types import (
    CapitalAllocationState,
    RolloutPhaseRule,
    StrategyCapitalRule,
    SymbolCapitalRule,
)

ROLLOUT_PHASE_ORDER = ["disabled", "micro", "limited", "scaled"]


def safe_float(value: float | int | None) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(numeric):
        return 0.0
    return round(numeric, 8)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def phase_index(phase: str) -> int:
    try:
        return ROLLOUT_PHASE_ORDER.index(str(phase).lower())
    except ValueError:
        return 0


def next_phase(phase: str) -> str:
    index = min(phase_index(phase) + 1, len(ROLLOUT_PHASE_ORDER) - 1)
    return ROLLOUT_PHASE_ORDER[index]


def previous_phase(phase: str) -> str:
    index = max(phase_index(phase) - 1, 0)
    return ROLLOUT_PHASE_ORDER[index]


def get_phase_rule(settings: Settings, phase: str) -> RolloutPhaseRule:
    normalized = str(phase or settings.live_phase_default).lower()
    initial = min(
        max(safe_float(settings.live_initial_capital_limit), 0.0),
        max(safe_float(settings.live_max_capital_total), 0.0),
    )
    limited = min(initial + max(safe_float(settings.live_scaling_step_capital), 0.0), safe_float(settings.live_max_capital_total))
    scaled = safe_float(settings.live_max_capital_total)
    rules = {
        "disabled": RolloutPhaseRule(
            phase="disabled",
            capital_limit=0.0,
            strict_approval_required=True,
            max_open_positions=0,
        ),
        "micro": RolloutPhaseRule(
            phase="micro",
            capital_limit=initial,
            strict_approval_required=True,
            max_open_positions=min(max(settings.live_portfolio_max_correlated_positions, 1), 1),
        ),
        "limited": RolloutPhaseRule(
            phase="limited",
            capital_limit=limited,
            strict_approval_required=True,
            max_open_positions=min(max(settings.live_portfolio_max_correlated_positions, 1), 2),
        ),
        "scaled": RolloutPhaseRule(
            phase="scaled",
            capital_limit=scaled,
            strict_approval_required=bool(settings.live_require_explicit_approval),
            max_open_positions=max(settings.live_portfolio_max_correlated_positions, 1),
        ),
    }
    return rules.get(normalized, rules["disabled"])


def compute_allowed_capital(settings: Settings, phase: str, requested_limit: float | None = None) -> float:
    phase_limit = get_phase_rule(settings, phase).capital_limit
    if requested_limit is None:
        return safe_float(phase_limit)
    return safe_float(min(max(requested_limit, 0.0), phase_limit, settings.live_max_capital_total))


def compute_allocation_state(
    open_positions: list[Position],
    *,
    capital_limit: float,
) -> CapitalAllocationState:
    strategy_allocations: dict[str, float] = {}
    symbol_allocations: dict[str, float] = {}
    deployed_capital = 0.0
    open_position_count = 0

    for position in open_positions:
        if position.status == "closed":
            continue
        position_notional = safe_float(position.entry_price * position.quantity_open)
        deployed_capital += position_notional
        open_position_count += 1
        strategy_allocations[position.strategy_name] = safe_float(
            strategy_allocations.get(position.strategy_name, 0.0) + position_notional
        )
        symbol_allocations[position.symbol] = safe_float(
            symbol_allocations.get(position.symbol, 0.0) + position_notional
        )

    deployed_capital = safe_float(deployed_capital)
    remaining = safe_float(max(capital_limit - deployed_capital, 0.0))
    return CapitalAllocationState(
        deployed_capital=deployed_capital,
        remaining_capital=remaining,
        open_position_count=open_position_count,
        strategy_allocations=strategy_allocations,
        symbol_allocations=symbol_allocations,
    )


def compute_live_performance_metrics(
    trades: list[Trade],
    *,
    starting_balance: float,
) -> dict[str, float]:
    resolved_balance = max(safe_float(starting_balance), 1.0)
    live_trades = [trade for trade in trades if trade.execution_mode == "live" and trade.closed_at is not None]
    if not live_trades:
        return {
            "trade_count": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "daily_loss_pct": 0.0,
            "weekly_loss_pct": 0.0,
            "failed_executions": 0.0,
            "reconciliation_mismatches": 0.0,
        }

    ordered = sorted(live_trades, key=lambda item: item.closed_at or item.updated_at)
    gross_profit = 0.0
    gross_loss = 0.0
    wins = 0
    failed_executions = 0
    reconciliation_mismatches = 0
    now = utc_now()
    equity = resolved_balance
    peak = resolved_balance
    max_drawdown_pct = 0.0
    daily_loss = 0.0
    weekly_loss = 0.0

    for trade in ordered:
        pnl = safe_float(trade.realized_pnl)
        equity = safe_float(equity + pnl)
        peak = max(peak, equity)
        drawdown_pct = safe_float(((peak - equity) / peak) * 100.0) if peak > 0 else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        if pnl > 0:
            wins += 1
            gross_profit = safe_float(gross_profit + pnl)
        elif pnl < 0:
            gross_loss = safe_float(gross_loss + abs(pnl))
        if trade.status in {"FAILED", "REJECTED"}:
            failed_executions += 1
        if trade.reconciliation_status == "mismatch":
            reconciliation_mismatches += 1
        closed_at = trade.closed_at or trade.updated_at
        if closed_at.date() == now.date() and pnl < 0:
            daily_loss = safe_float(daily_loss + abs(pnl))
        trade_year, trade_week, _ = closed_at.isocalendar()
        now_year, now_week, _ = now.isocalendar()
        if (trade_year, trade_week) == (now_year, now_week) and pnl < 0:
            weekly_loss = safe_float(weekly_loss + abs(pnl))

    trade_count = len(ordered)
    win_rate = safe_float((wins / trade_count) * 100.0) if trade_count > 0 else 0.0
    profit_factor = safe_float(gross_profit / gross_loss) if gross_loss > 0 else (safe_float(gross_profit) if gross_profit > 0 else 0.0)
    return {
        "trade_count": float(trade_count),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": safe_float(max_drawdown_pct),
        "daily_loss_pct": safe_float((daily_loss / resolved_balance) * 100.0),
        "weekly_loss_pct": safe_float((weekly_loss / resolved_balance) * 100.0),
        "failed_executions": float(failed_executions),
        "reconciliation_mismatches": float(reconciliation_mismatches),
    }


def can_scale_up(
    settings: Settings,
    *,
    current_phase: str,
    trades: list[Trade],
) -> tuple[bool, list[str]]:
    if current_phase == "scaled":
        return False, ["already_at_max_phase"]
    if current_phase == "disabled":
        return True, []

    metrics = compute_live_performance_metrics(
        trades,
        starting_balance=settings.paper_account_start_balance,
    )
    reasons: list[str] = []
    if metrics["trade_count"] < settings.live_scaling_min_trades:
        reasons.append("insufficient_live_trade_count")
    if metrics["win_rate"] < settings.live_scaling_min_win_rate:
        reasons.append("win_rate_below_threshold")
    if metrics["profit_factor"] < settings.live_scaling_min_profit_factor:
        reasons.append("profit_factor_below_threshold")
    if metrics["max_drawdown_pct"] > settings.live_scaling_max_drawdown_pct:
        reasons.append("drawdown_above_threshold")
    if metrics["daily_loss_pct"] > settings.live_scaling_max_daily_loss_pct:
        reasons.append("daily_loss_above_threshold")
    if metrics["weekly_loss_pct"] > settings.live_scaling_max_weekly_loss_pct:
        reasons.append("weekly_loss_above_threshold")
    return len(reasons) == 0, reasons


def can_scale_down(
    settings: Settings,
    *,
    trades: list[Trade],
    manual: bool = False,
) -> tuple[bool, list[str], bool]:
    if manual:
        return True, ["manual_rollback"], True

    metrics = compute_live_performance_metrics(
        trades,
        starting_balance=settings.paper_account_start_balance,
    )
    reasons: list[str] = []
    critical = False
    if metrics["daily_loss_pct"] > settings.live_scaling_max_daily_loss_pct:
        reasons.append("daily_loss_threshold_breached")
    if metrics["weekly_loss_pct"] > settings.live_scaling_max_weekly_loss_pct:
        reasons.append("weekly_loss_threshold_breached")
    if metrics["max_drawdown_pct"] > settings.live_scaling_max_drawdown_pct:
        reasons.append("drawdown_threshold_breached")
        critical = True
    if metrics["failed_executions"] >= 3:
        reasons.append("repeated_failed_executions")
        critical = True
    if metrics["reconciliation_mismatches"] >= 2:
        reasons.append("repeated_reconciliation_mismatches")
        critical = True
    return len(reasons) > 0, reasons, critical


def validate_strategy_cap(
    settings: Settings,
    *,
    allowed_capital: float,
    strategy_name: str,
    requested_notional: float,
    strategy_allocations: dict[str, float],
) -> tuple[bool, StrategyCapitalRule]:
    max_capital_amount = safe_float(allowed_capital * settings.live_strategy_max_capital_pct / 100.0)
    current = safe_float(strategy_allocations.get(strategy_name, 0.0))
    rule = StrategyCapitalRule(
        strategy_name=strategy_name,
        max_capital_pct=safe_float(settings.live_strategy_max_capital_pct),
        max_capital_amount=max_capital_amount,
    )
    return safe_float(current + requested_notional) <= max_capital_amount, rule


def validate_symbol_cap(
    settings: Settings,
    *,
    allowed_capital: float,
    symbol: str,
    requested_notional: float,
    symbol_allocations: dict[str, float],
) -> tuple[bool, SymbolCapitalRule]:
    max_capital_amount = safe_float(allowed_capital * settings.live_symbol_max_capital_pct / 100.0)
    current = safe_float(symbol_allocations.get(symbol, 0.0))
    rule = SymbolCapitalRule(
        symbol=symbol,
        max_capital_pct=safe_float(settings.live_symbol_max_capital_pct),
        max_capital_amount=max_capital_amount,
    )
    return safe_float(current + requested_notional) <= max_capital_amount, rule


def validate_portfolio_capital(
    settings: Settings,
    *,
    phase_rule: RolloutPhaseRule,
    allocation_state: CapitalAllocationState,
    requested_notional: float,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if safe_float(allocation_state.deployed_capital + requested_notional) > safe_float(phase_rule.capital_limit):
        reasons.append("rollout_capital_limit_exceeded")
    max_positions = min(
        max(settings.live_portfolio_max_correlated_positions, 0),
        max(phase_rule.max_open_positions, 0),
    )
    if allocation_state.open_position_count >= max_positions and max_positions >= 0:
        reasons.append("portfolio_concentration_limit_exceeded")
    return len(reasons) == 0, reasons

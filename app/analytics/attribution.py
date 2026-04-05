from __future__ import annotations

from collections import defaultdict

from app.analytics.metrics import (
    average_holding_minutes,
    capital_efficiency,
    expectancy,
    execution_mode_split,
    max_drawdown_pct,
    trade_win_rate,
)
from app.analytics.regime import classify_regime
from app.analytics.types import PortfolioMetrics, StrategyAttribution, SymbolAttribution
from app.config.settings import Settings
from app.execution.types import Trade
from app.persistence.db import safe_float, utc_now


def _filter_closed(trades: list[Trade], execution_mode: str | None = None) -> list[Trade]:
    return [
        trade
        for trade in trades
        if trade.closed_at is not None and (execution_mode is None or trade.execution_mode == execution_mode)
    ]


def build_strategy_attribution(
    trades: list[Trade],
    *,
    settings: Settings,
    execution_mode: str | None = None,
) -> list[StrategyAttribution]:
    closed = _filter_closed(trades, execution_mode)
    total_pnl = safe_float(sum(safe_float(trade.realized_pnl) for trade in closed))
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in closed:
        groups[trade.strategy_name].append(trade)
    items: list[StrategyAttribution] = []
    for strategy_name, group in sorted(groups.items()):
        pnl_total = safe_float(sum(safe_float(trade.realized_pnl) for trade in group))
        regime = classify_regime(
            group,
            volatility_lookback=settings.regime_volatility_lookback,
            trend_lookback=settings.regime_trend_lookback,
        )
        items.append(
            StrategyAttribution(
                strategy_name=strategy_name,
                total_pnl=pnl_total,
                win_rate=trade_win_rate(group),
                expectancy=expectancy(group),
                drawdown_pct=max_drawdown_pct(group, starting_balance=settings.paper_account_start_balance),
                capital_efficiency=capital_efficiency(group),
                average_holding_minutes=average_holding_minutes(group),
                trade_count=len(group),
                contribution_pct=safe_float((pnl_total / total_pnl) * 100.0) if total_pnl != 0 else 0.0,
                regime_breakdown={regime: pnl_total},
            )
        )
    items.sort(key=lambda item: (-item.total_pnl, item.strategy_name))
    return items


def build_symbol_attribution(
    trades: list[Trade],
    *,
    execution_mode: str | None = None,
) -> list[SymbolAttribution]:
    closed = _filter_closed(trades, execution_mode)
    total_pnl = safe_float(sum(safe_float(trade.realized_pnl) for trade in closed))
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in closed:
        groups[trade.symbol].append(trade)
    items: list[SymbolAttribution] = []
    for symbol, group in sorted(groups.items()):
        pnl_total = safe_float(sum(safe_float(trade.realized_pnl) for trade in group))
        items.append(
            SymbolAttribution(
                symbol=symbol,
                total_pnl=pnl_total,
                win_rate=trade_win_rate(group),
                trade_count=len(group),
                contribution_pct=safe_float((pnl_total / total_pnl) * 100.0) if total_pnl != 0 else 0.0,
                average_holding_minutes=average_holding_minutes(group),
                execution_mode_split=execution_mode_split(group),
            )
        )
    items.sort(key=lambda item: (-item.total_pnl, item.symbol))
    return items


def build_portfolio_metrics(
    trades: list[Trade],
    *,
    settings: Settings,
    execution_mode: str | None = None,
) -> PortfolioMetrics:
    closed = _filter_closed(trades, execution_mode)
    return PortfolioMetrics(
        total_pnl=safe_float(sum(safe_float(trade.realized_pnl) for trade in closed)),
        total_trades=len(closed),
        win_rate=trade_win_rate(closed),
        expectancy=expectancy(closed),
        drawdown_pct=max_drawdown_pct(closed, starting_balance=settings.paper_account_start_balance),
        execution_mode_split=execution_mode_split(closed),
        top_strategies=build_strategy_attribution(closed, settings=settings, execution_mode=execution_mode)[:5],
        top_symbols=build_symbol_attribution(closed, execution_mode=execution_mode)[:5],
        current_regime=classify_regime(
            closed,
            volatility_lookback=settings.regime_volatility_lookback,
            trend_lookback=settings.regime_trend_lookback,
        ),
        lookback_days=settings.analytics_lookback_days,
        timestamp=utc_now(),
    )

from __future__ import annotations

from collections import defaultdict

from app.config.settings import Settings
from app.persistence.db import safe_float
from app.portfolio.state import resolve_cluster
from app.portfolio.types import PortfolioState


def pct_cap(base_amount: float, pct: float) -> float:
    return safe_float(base_amount * pct / 100.0)


def active_pending_capital(state: PortfolioState) -> float:
    return safe_float(
        sum(
            item.allocated_capital
            for item in state.pending_allocations
            if item.decision in {"approved", "reduced"}
        )
    )


def active_pending_positions(state: PortfolioState) -> int:
    return sum(1 for item in state.pending_allocations if item.decision in {"approved", "reduced"})


def strategy_headroom(settings: Settings, state: PortfolioState, strategy_name: str) -> float:
    allocation = state.strategy_allocations.get(strategy_name)
    used = safe_float(allocation.deployed_capital + allocation.pending_capital) if allocation else 0.0
    cap_amount = pct_cap(state.total_equity, settings.portfolio_max_per_strategy_pct)
    return safe_float(max(cap_amount - used, 0.0))


def symbol_headroom(settings: Settings, state: PortfolioState, symbol: str) -> float:
    allocation = state.symbol_allocations.get(symbol)
    used = safe_float(allocation.deployed_capital + allocation.pending_capital) if allocation else 0.0
    cap_amount = pct_cap(state.total_equity, settings.portfolio_max_per_symbol_pct)
    return safe_float(max(cap_amount - used, 0.0))


def cluster_headroom(settings: Settings, state: PortfolioState, symbol: str) -> tuple[str, float]:
    cluster_name = resolve_cluster(symbol, settings.portfolio_correlation_mode)
    allocation = state.correlation_clusters.get(cluster_name)
    used = safe_float(allocation.deployed_capital) if allocation else 0.0
    cap_amount = pct_cap(state.total_equity, settings.portfolio_max_correlated_cluster_pct)
    return cluster_name, safe_float(max(cap_amount - used, 0.0))


def portfolio_total_headroom(settings: Settings, state: PortfolioState) -> float:
    max_total = pct_cap(state.total_equity, settings.portfolio_max_total_capital_pct)
    used = safe_float(state.deployed_capital + active_pending_capital(state))
    return safe_float(max(max_total - used, 0.0))


def single_trade_cap(settings: Settings, state: PortfolioState) -> float:
    return pct_cap(state.total_equity, settings.portfolio_max_single_trade_pct)


def detect_static_conflicts(
    state: PortfolioState,
    *,
    symbol: str,
    side: str,
) -> list[str]:
    reasons: list[str] = []
    existing_sides = [item.lower() for item in state.position_sides_by_symbol.get(symbol, [])]
    normalized_side = side.lower()
    if existing_sides and any(item != normalized_side for item in existing_sides):
        reasons.append("conflicting_symbol_side")
    return reasons


def build_cap_reasons(
    settings: Settings,
    state: PortfolioState,
    *,
    symbol: str,
    strategy_name: str,
    requested_capital: float,
    rollout_capital_limit: float | None = None,
) -> tuple[list[str], dict[str, float | str]]:
    reasons: list[str] = []
    cluster_name, cluster_room = cluster_headroom(settings, state, symbol)
    total_room = portfolio_total_headroom(settings, state)
    strategy_room = strategy_headroom(settings, state, strategy_name)
    symbol_room = symbol_headroom(settings, state, symbol)
    trade_room = single_trade_cap(settings, state)
    free_cash_room = safe_float(state.free_cash)
    rollout_room = safe_float(rollout_capital_limit) if rollout_capital_limit is not None else requested_capital

    if active_pending_positions(state) + state.open_positions_count >= settings.portfolio_max_open_positions:
        reasons.append("max_open_positions_exceeded")
    if free_cash_room <= 0:
        reasons.append("reserve_cash_floor_reached")
    if total_room <= 0:
        reasons.append("portfolio_total_cap_exceeded")
    if strategy_room <= 0:
        reasons.append("strategy_cap_exceeded")
    if symbol_room <= 0:
        reasons.append("symbol_cap_exceeded")
    if cluster_room <= 0:
        reasons.append("cluster_cap_exceeded")
    if trade_room <= 0:
        reasons.append("single_trade_cap_exceeded")
    if rollout_capital_limit is not None and rollout_room <= 0:
        reasons.append("rollout_cap_exceeded")

    return reasons, {
        "cluster_name": cluster_name,
        "total_room": total_room,
        "strategy_room": strategy_room,
        "symbol_room": symbol_room,
        "cluster_room": cluster_room,
        "trade_room": trade_room,
        "free_cash_room": free_cash_room,
        "rollout_room": rollout_room,
    }


def summarize_denials(decisions: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for decision in decisions:
        for reason in decision.get("reasons", []):
            counts[str(reason)] += 1
    return dict(sorted(counts.items()))

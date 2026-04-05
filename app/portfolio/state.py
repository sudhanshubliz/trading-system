from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.config.settings import Settings
from app.execution.types import Approval, Position, Trade
from app.persistence.db import safe_float, utc_now
from app.portfolio.types import (
    CandidateAllocation,
    CorrelationClusterState,
    PortfolioState,
    StrategyAllocation,
    SymbolAllocation,
)

MAJORS_CLUSTER = {"BTCUSDT", "ETHUSDT"}


def resolve_cluster(symbol: str, mode: str = "simple") -> str:
    normalized = str(symbol).upper()
    if mode != "simple":
        return normalized.lower()
    if normalized in MAJORS_CLUSTER:
        return "majors"
    return normalized.lower()


class PortfolioStateManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_state(
        self,
        *,
        positions: list[Position],
        trades: list[Trade],
        approvals: list[Approval],
        pending_allocations: list[CandidateAllocation],
        active_rollout_phase: str,
        execution_mode: str,
    ) -> PortfolioState:
        open_positions = [item for item in positions if item.status != "closed"]
        total_equity = self._compute_total_equity(open_positions, trades, execution_mode=execution_mode)
        reserved_cash = safe_float(total_equity * self.settings.portfolio_reserve_cash_pct / 100.0)
        deployed_capital = safe_float(
            sum(safe_float(position.entry_price * position.quantity_open) for position in open_positions)
        )
        free_cash = safe_float(max(total_equity - reserved_cash - deployed_capital, 0.0))

        open_positions_by_symbol: dict[str, int] = defaultdict(int)
        open_positions_by_strategy: dict[str, int] = defaultdict(int)
        position_sides_by_symbol: dict[str, list[str]] = defaultdict(list)
        strategy_capital: dict[str, float] = defaultdict(float)
        symbol_capital: dict[str, float] = defaultdict(float)
        strategy_pnl: dict[str, float] = defaultdict(float)
        symbol_pnl: dict[str, float] = defaultdict(float)
        cluster_capital: dict[str, float] = defaultdict(float)
        cluster_symbols: dict[str, set[str]] = defaultdict(set)

        for position in open_positions:
            open_positions_by_symbol[position.symbol] += 1
            open_positions_by_strategy[position.strategy_name] += 1
            position_sides_by_symbol[position.symbol].append(position.side)
            notional = safe_float(position.entry_price * position.quantity_open)
            strategy_capital[position.strategy_name] += notional
            symbol_capital[position.symbol] += notional
            cluster_name = resolve_cluster(position.symbol, self.settings.portfolio_correlation_mode)
            cluster_capital[cluster_name] += notional
            cluster_symbols[cluster_name].add(position.symbol)

        for trade in trades:
            if trade.execution_mode != execution_mode:
                continue
            strategy_pnl[trade.strategy_name] += safe_float(trade.realized_pnl)
            symbol_pnl[trade.symbol] += safe_float(trade.realized_pnl)

        strategy_allocations = {
            key: StrategyAllocation(
                strategy_name=key,
                deployed_capital=safe_float(value),
                pending_capital=safe_float(
                    sum(
                        item.allocated_capital
                        for item in pending_allocations
                        if item.strategy_name == key and item.decision in {"approved", "reduced"}
                    )
                ),
                allocation_pct=safe_float((value / total_equity) * 100.0) if total_equity > 0 else 0.0,
                open_positions=open_positions_by_strategy.get(key, 0),
                pnl_total=safe_float(strategy_pnl.get(key, 0.0)),
            )
            for key, value in strategy_capital.items()
        }
        symbol_allocations = {
            key: SymbolAllocation(
                symbol=key,
                deployed_capital=safe_float(value),
                pending_capital=safe_float(
                    sum(
                        item.allocated_capital
                        for item in pending_allocations
                        if item.symbol == key and item.decision in {"approved", "reduced"}
                    )
                ),
                allocation_pct=safe_float((value / total_equity) * 100.0) if total_equity > 0 else 0.0,
                open_positions=open_positions_by_symbol.get(key, 0),
                pnl_total=safe_float(symbol_pnl.get(key, 0.0)),
            )
            for key, value in symbol_capital.items()
        }
        correlation_clusters = {
            key: CorrelationClusterState(
                cluster_name=key,
                symbols=sorted(cluster_symbols.get(key, set())),
                deployed_capital=safe_float(value),
                max_capital=safe_float(total_equity * self.settings.portfolio_max_correlated_cluster_pct / 100.0),
                allocation_pct=safe_float((value / total_equity) * 100.0) if total_equity > 0 else 0.0,
            )
            for key, value in cluster_capital.items()
        }
        return PortfolioState(
            total_equity=total_equity,
            free_cash=free_cash,
            reserved_cash=reserved_cash,
            deployed_capital=deployed_capital,
            open_positions_count=len(open_positions),
            open_positions_by_symbol=dict(sorted(open_positions_by_symbol.items())),
            open_positions_by_strategy=dict(sorted(open_positions_by_strategy.items())),
            pending_allocations=list(pending_allocations),
            active_rollout_phase=active_rollout_phase,
            execution_mode=execution_mode,
            strategy_allocations=dict(sorted(strategy_allocations.items())),
            symbol_allocations=dict(sorted(symbol_allocations.items())),
            correlation_clusters=dict(sorted(correlation_clusters.items())),
            pending_candidate_count=len(approvals),
            rejected_candidate_count=sum(1 for item in pending_allocations if item.decision == "rejected"),
            position_sides_by_symbol={key: sorted(value) for key, value in sorted(position_sides_by_symbol.items())},
            timestamp=utc_now(),
        )

    def apply_candidate_allocation(
        self,
        state: PortfolioState,
        candidate: CandidateAllocation,
    ) -> PortfolioState:
        state.pending_allocations.append(candidate)
        if candidate.decision not in {"approved", "reduced"}:
            state.rejected_candidate_count += 1
            return state

        state.free_cash = safe_float(max(state.free_cash - candidate.allocated_capital, 0.0))
        state.pending_candidate_count = max(state.pending_candidate_count - 1, 0)

        strategy_item = state.strategy_allocations.get(candidate.strategy_name)
        if strategy_item is None:
            strategy_item = StrategyAllocation(
                strategy_name=candidate.strategy_name,
                deployed_capital=0.0,
                pending_capital=0.0,
                allocation_pct=0.0,
                open_positions=0,
                pnl_total=0.0,
            )
            state.strategy_allocations[candidate.strategy_name] = strategy_item
        strategy_item.pending_capital = safe_float(strategy_item.pending_capital + candidate.allocated_capital)

        symbol_item = state.symbol_allocations.get(candidate.symbol)
        if symbol_item is None:
            symbol_item = SymbolAllocation(
                symbol=candidate.symbol,
                deployed_capital=0.0,
                pending_capital=0.0,
                allocation_pct=0.0,
                open_positions=0,
                pnl_total=0.0,
            )
            state.symbol_allocations[candidate.symbol] = symbol_item
        symbol_item.pending_capital = safe_float(symbol_item.pending_capital + candidate.allocated_capital)

        cluster_name = candidate.cluster_name or resolve_cluster(
            candidate.symbol,
            self.settings.portfolio_correlation_mode,
        )
        cluster_item = state.correlation_clusters.get(cluster_name)
        if cluster_item is None:
            cluster_item = CorrelationClusterState(
                cluster_name=cluster_name,
                symbols=[candidate.symbol],
                deployed_capital=0.0,
                max_capital=safe_float(
                    state.total_equity * self.settings.portfolio_max_correlated_cluster_pct / 100.0
                ),
                allocation_pct=0.0,
            )
            state.correlation_clusters[cluster_name] = cluster_item
        if candidate.symbol not in cluster_item.symbols:
            cluster_item.symbols.append(candidate.symbol)
            cluster_item.symbols.sort()
        cluster_item.deployed_capital = safe_float(cluster_item.deployed_capital + candidate.allocated_capital)
        cluster_item.allocation_pct = (
            safe_float((cluster_item.deployed_capital / state.total_equity) * 100.0) if state.total_equity > 0 else 0.0
        )
        return state

    def _compute_total_equity(
        self,
        positions: Iterable[Position],
        trades: Iterable[Trade],
        *,
        execution_mode: str,
    ) -> float:
        baseline = safe_float(self.settings.paper_account_start_balance)
        realized = safe_float(
            sum(
                safe_float(trade.realized_pnl)
                for trade in trades
                if trade.execution_mode == execution_mode
            )
        )
        unrealized = safe_float(
            sum(
                safe_float(position.unrealized_pnl)
                for position in positions
                if position.execution_mode == execution_mode
            )
        )
        return safe_float(max(baseline + realized + unrealized, 0.0))

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class StrategyAllocation:
    strategy_name: str
    deployed_capital: float
    pending_capital: float
    allocation_pct: float
    open_positions: int
    pnl_total: float = 0.0


@dataclass(slots=True)
class SymbolAllocation:
    symbol: str
    deployed_capital: float
    pending_capital: float
    allocation_pct: float
    open_positions: int
    pnl_total: float = 0.0


@dataclass(slots=True)
class CorrelationClusterState:
    cluster_name: str
    symbols: list[str] = field(default_factory=list)
    deployed_capital: float = 0.0
    max_capital: float = 0.0
    allocation_pct: float = 0.0


@dataclass(slots=True)
class CandidateAllocation:
    assessment_id: str
    symbol: str
    strategy_name: str
    side: str
    requested_capital: float
    allocated_capital: float
    allocated_quantity: float
    score: float
    decision: str
    reasons: list[str] = field(default_factory=list)
    cluster_name: str | None = None
    execution_mode: str = "paper"


@dataclass(slots=True)
class PortfolioDecision:
    assessment_id: str
    symbol: str
    strategy_name: str
    side: str
    allowed: bool
    decision: str
    allocated_capital: float
    allocated_quantity: float
    requested_capital: float
    score: float
    ranking_index: int
    reasons: list[str] = field(default_factory=list)
    cluster_name: str | None = None
    execution_mode: str = "paper"
    timestamp: datetime | None = None


@dataclass(slots=True)
class PortfolioState:
    total_equity: float
    free_cash: float
    reserved_cash: float
    deployed_capital: float
    open_positions_count: int
    open_positions_by_symbol: dict[str, int] = field(default_factory=dict)
    open_positions_by_strategy: dict[str, int] = field(default_factory=dict)
    pending_allocations: list[CandidateAllocation] = field(default_factory=list)
    active_rollout_phase: str = "disabled"
    execution_mode: str = "paper"
    strategy_allocations: dict[str, StrategyAllocation] = field(default_factory=dict)
    symbol_allocations: dict[str, SymbolAllocation] = field(default_factory=dict)
    correlation_clusters: dict[str, CorrelationClusterState] = field(default_factory=dict)
    pending_candidate_count: int = 0
    rejected_candidate_count: int = 0
    position_sides_by_symbol: dict[str, list[str]] = field(default_factory=dict)
    timestamp: datetime | None = None

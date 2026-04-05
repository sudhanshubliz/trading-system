from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CandidateAllocationResponse(BaseModel):
    assessment_id: str
    symbol: str
    strategy_name: str
    side: str
    requested_capital: float
    allocated_capital: float
    allocated_quantity: float
    score: float
    decision: str
    reasons: list[str] = Field(default_factory=list)
    cluster_name: str | None = None
    execution_mode: str = "paper"


class StrategyAllocationResponse(BaseModel):
    strategy_name: str
    deployed_capital: float
    pending_capital: float
    allocation_pct: float
    open_positions: int
    pnl_total: float = 0.0


class SymbolAllocationResponse(BaseModel):
    symbol: str
    deployed_capital: float
    pending_capital: float
    allocation_pct: float
    open_positions: int
    pnl_total: float = 0.0


class CorrelationClusterStateResponse(BaseModel):
    cluster_name: str
    symbols: list[str] = Field(default_factory=list)
    deployed_capital: float = 0.0
    max_capital: float = 0.0
    allocation_pct: float = 0.0


class PortfolioDecisionResponse(BaseModel):
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
    reasons: list[str] = Field(default_factory=list)
    cluster_name: str | None = None
    execution_mode: str = "paper"
    timestamp: datetime | None = None


class PortfolioStatusResponse(BaseModel):
    total_equity: float
    free_cash: float
    reserved_cash: float
    deployed_capital: float
    open_positions_count: int
    open_positions_by_symbol: dict[str, int] = Field(default_factory=dict)
    open_positions_by_strategy: dict[str, int] = Field(default_factory=dict)
    pending_allocations: list[CandidateAllocationResponse] = Field(default_factory=list)
    active_rollout_phase: str
    execution_mode: str
    strategy_allocations: dict[str, StrategyAllocationResponse] = Field(default_factory=dict)
    symbol_allocations: dict[str, SymbolAllocationResponse] = Field(default_factory=dict)
    correlation_clusters: dict[str, CorrelationClusterStateResponse] = Field(default_factory=dict)
    pending_candidate_count: int
    rejected_candidate_count: int
    position_sides_by_symbol: dict[str, list[str]] = Field(default_factory=dict)
    timestamp: datetime | None = None


class PortfolioAllocationsResponse(BaseModel):
    execution_mode: str
    deployed_capital: float
    free_cash: float
    reserved_cash: float
    strategy_allocations: dict[str, StrategyAllocationResponse] = Field(default_factory=dict)
    symbol_allocations: dict[str, SymbolAllocationResponse] = Field(default_factory=dict)
    correlation_clusters: dict[str, CorrelationClusterStateResponse] = Field(default_factory=dict)
    pending_candidate_count: int
    rejected_candidate_count: int
    timestamp: datetime | None = None


class PortfolioEvaluateRequest(BaseModel):
    assessment_ids: list[str] = Field(default_factory=list)
    execution_mode: str = "paper"


class PortfolioEvaluateResponse(BaseModel):
    execution_mode: str
    state: PortfolioStatusResponse
    decisions: list[PortfolioDecisionResponse] = Field(default_factory=list)
    selected_count: int
    rejected_count: int
    denial_summary: dict[str, int] = Field(default_factory=dict)
    snapshot_id: str | None = None
    timestamp: datetime


class PortfolioRebalanceResponse(BaseModel):
    execution_mode: str
    enabled: bool
    actions: list[dict[str, str | float]] = Field(default_factory=list)
    action_count: int
    timestamp: datetime


class PortfolioHistoryResponse(BaseModel):
    items: list[dict[str, object]]
    count: int

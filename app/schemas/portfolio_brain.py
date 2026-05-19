from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AllocationRecommendationResponse(BaseModel):
    allocation_id: str
    strategy_name: str
    scope_key: str
    capital_pct: float
    status: str
    explanation: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class PortfolioBrainSnapshotResponse(BaseModel):
    snapshot_id: str
    execution_mode: str
    generated_at: datetime
    capital_by_strategy_family: dict[str, float] = Field(default_factory=dict)
    capital_by_symbol_or_market: dict[str, float] = Field(default_factory=dict)
    gross_exposure_cap: float
    net_exposure_guidance: float
    strategy_throttles: dict[str, float] = Field(default_factory=dict)
    strategy_disables: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class AllocationRecommendationListResponse(BaseModel):
    items: list[AllocationRecommendationResponse] = Field(default_factory=list)
    count: int


class PortfolioBrainHistoryResponse(BaseModel):
    items: list[PortfolioBrainSnapshotResponse] = Field(default_factory=list)
    count: int


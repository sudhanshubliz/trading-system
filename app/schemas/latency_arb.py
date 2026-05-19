from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LatencyArbOpportunityResponse(BaseModel):
    opportunity_id: str
    market_id: str
    market_title: str
    symbol: str
    timestamp: datetime
    fair_probability: float
    market_probability: float
    gross_edge_bps: float
    fee_estimate_bps: float
    slippage_estimate_bps: float
    net_edge_bps: float
    confidence: float
    depth_usd: float
    spread_bps: float | None = None
    time_to_expiry_seconds: float
    tradable: bool
    recommended_direction: str
    explanation: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class LatencyArbOpportunityListResponse(BaseModel):
    items: list[LatencyArbOpportunityResponse] = Field(default_factory=list)
    count: int


class LatencyArbSummaryResponse(BaseModel):
    count: int
    tradable_count: int
    symbols: list[str] = Field(default_factory=list)
    top_net_edge_bps: float

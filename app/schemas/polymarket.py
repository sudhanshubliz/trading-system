from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PolymarketMarketResponse(BaseModel):
    market_id: str
    title: str
    category: str
    event_slug: str
    status: str
    close_time: datetime | None = None
    last_updated_at: datetime
    yes_price: float | None = None
    no_price: float | None = None
    linked_group: str | None = None
    linked_rule: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class PolymarketMarketListResponse(BaseModel):
    items: list[PolymarketMarketResponse] = Field(default_factory=list)
    count: int


class PolymarketOpportunityResponse(BaseModel):
    opportunity_id: str = Field(alias="id")
    market_id: str
    market_title: str
    timestamp: datetime
    signal_family: str
    opportunity_type: str
    yes_price: float | None = None
    no_price: float | None = None
    yes_plus_no: float | None = None
    deviation_from_one: float | None = None
    spread: float | None = None
    liquidity_estimate: float | None = None
    stale_market: bool
    gross_edge_estimate: float
    fee_estimate: float
    slippage_estimate: float
    net_edge_estimate: float
    confidence: float
    tradable: bool
    recommended_direction: str
    expected_holding_period: str
    explanation: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class PolymarketOpportunityListResponse(BaseModel):
    items: list[PolymarketOpportunityResponse] = Field(default_factory=list)
    count: int


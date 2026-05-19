from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ArbitrageOpportunityResponse(BaseModel):
    opportunity_id: str = Field(alias="id")
    signal_family: str
    timestamp: datetime
    opportunity_type: str
    tradable: bool
    confidence: float
    recommended_direction: str
    expected_holding_period: str
    gross_edge_estimate: float
    fee_estimate: float
    slippage_estimate: float
    net_edge_estimate: float
    explanation: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    symbol: str | None = None
    market_id: str | None = None
    market_title: str | None = None
    basis_value: float | None = None
    funding_value: float | None = None
    basis_zscore: float | None = None
    funding_zscore: float | None = None
    yes_price: float | None = None
    no_price: float | None = None
    yes_plus_no: float | None = None
    deviation_from_one: float | None = None
    spread: float | None = None
    liquidity_estimate: float | None = None
    stale_market: bool | None = None


class ArbitrageOpportunityListResponse(BaseModel):
    items: list[ArbitrageOpportunityResponse] = Field(default_factory=list)
    count: int


class BasisFundingOpportunityResponse(ArbitrageOpportunityResponse):
    symbol: str


class BasisFundingOpportunityListResponse(ArbitrageOpportunityListResponse):
    items: list[BasisFundingOpportunityResponse] = Field(default_factory=list)

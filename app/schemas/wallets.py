from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WalletProfileResponse(BaseModel):
    wallet_id: str
    provider: str
    first_seen: datetime
    last_seen: datetime
    market_count: int
    trade_count: int
    estimated_hit_rate: float
    estimated_pnl_score: float
    timing_score: float
    sizing_discipline_score: float
    concentration_score: float
    crowding_score: float
    persistence_score: float
    quality_score: float
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class WalletObservationResponse(BaseModel):
    observation_id: str
    wallet_id: str
    provider: str
    observed_at: datetime
    market_or_symbol: str
    action: str
    inferred_direction: str
    inferred_conviction: float
    sizing_bucket: str
    latency_seconds: float | None = None
    associated_event: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class WalletSignalResponse(BaseModel):
    signal_id: str
    wallet_id: str
    symbol_or_market: str
    timestamp: datetime
    direction: str
    confidence: float
    rationale: list[str] = Field(default_factory=list)
    quality_score_snapshot: float
    crowding_risk: float
    recommended_action: str
    metadata: dict[str, object] = Field(default_factory=dict)


class WalletProfileListResponse(BaseModel):
    items: list[WalletProfileResponse] = Field(default_factory=list)
    count: int


class WalletObservationListResponse(BaseModel):
    items: list[WalletObservationResponse] = Field(default_factory=list)
    count: int


class WalletSignalListResponse(BaseModel):
    items: list[WalletSignalResponse] = Field(default_factory=list)
    count: int


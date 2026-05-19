from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RegimeSnapshotResponse(BaseModel):
    snapshot_id: str
    symbol: str
    regime: str
    confidence: float
    generated_at: datetime
    trend_score: float
    volatility_score: float
    compression_score: float
    mean_reversion_score: float
    supporting_factors: list[str] = Field(default_factory=list)
    veto_factors: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class RegimeSnapshotListResponse(BaseModel):
    items: list[RegimeSnapshotResponse] = Field(default_factory=list)
    count: int

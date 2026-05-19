from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProviderHealthResponse(BaseModel):
    snapshot_id: str
    provider_name: str
    status: str
    latency_ms: float | None = None
    success_rate: float
    stale_data_flag: bool
    error_count: int
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    observed_at: datetime
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class ProviderHealthListResponse(BaseModel):
    items: list[ProviderHealthResponse] = Field(default_factory=list)
    count: int


class ProviderHealthSummaryResponse(BaseModel):
    items: list[ProviderHealthResponse] = Field(default_factory=list)
    count: int
    healthy: int
    degraded: int
    unhealthy: int


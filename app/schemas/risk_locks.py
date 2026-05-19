from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RiskLockEventResponse(BaseModel):
    event_id: str
    lock_key: str
    lock_type: str
    scope: str
    scope_key: str
    severity: str
    reason: str
    metrics_snapshot: dict[str, object] = Field(default_factory=dict)
    is_active: bool
    triggered_at: datetime | None = None
    released_at: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class RiskLockEventListResponse(BaseModel):
    items: list[RiskLockEventResponse] = Field(default_factory=list)
    count: int

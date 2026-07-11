from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ShadowStatusResponse(BaseModel):
    running: bool
    auto_approve: bool
    execution_mode: str
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    cycle_count: int = 0
    last_cycle_at: datetime | None = None
    last_error: str | None = None
    blocked_reason: str | None = None
    evidence: dict[str, object] = Field(default_factory=dict)
    timestamp: datetime

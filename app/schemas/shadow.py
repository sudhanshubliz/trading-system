from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ShadowStatusResponse(BaseModel):
    running: bool
    auto_approve: bool
    execution_mode: str
    last_cycle_at: datetime | None = None
    last_error: str | None = None
    blocked_reason: str | None = None
    timestamp: datetime

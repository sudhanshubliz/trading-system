from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ComponentStatus(BaseModel):
    database: str
    persistence: str | None = None
    event_store: str | None = None
    market_data: str | None = None
    live_controller: str | None = None
    recovery: str | None = None
    startup_checks: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    mode: str
    global_pause: bool
    components: ComponentStatus
    alive: bool = True
    ready: bool = True
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    timestamp: datetime


class LivenessResponse(BaseModel):
    status: str
    alive: bool
    timestamp: datetime


class ReadinessCheckResponse(BaseModel):
    name: str
    status: str
    message: str
    critical: bool
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ReadinessResponse(BaseModel):
    status: str
    ready: bool
    boot_ready: bool
    checks: list[ReadinessCheckResponse]
    timestamp: datetime

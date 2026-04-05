from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RolloutStatusResponse(BaseModel):
    current_phase: str
    current_capital_limit: float
    allowed_capital_limit: float
    deployed_capital: float
    remaining_capital: float
    strategy_allocations: dict[str, float] = Field(default_factory=dict)
    symbol_allocations: dict[str, float] = Field(default_factory=dict)
    rollback_active: bool
    last_phase_change_at: datetime | None = None
    changed_by: str | None = None
    reason: str | None = None
    notes: list[str] = Field(default_factory=list)
    live_effectively_allowed: bool
    timestamp: datetime


class RolloutHistoryEntryResponse(BaseModel):
    event_type: str
    phase: str
    capital_limit: float
    changed_by: str | None = None
    reason: str | None = None
    rollback_active: bool
    timestamp: datetime | None = None


class RolloutHistoryResponse(BaseModel):
    items: list[RolloutHistoryEntryResponse]
    count: int


class RolloutCapitalResponse(BaseModel):
    current_phase: str
    current_capital_limit: float
    allowed_capital_limit: float
    deployed_capital: float
    remaining_capital: float
    strategy_allocations: dict[str, float] = Field(default_factory=dict)
    symbol_allocations: dict[str, float] = Field(default_factory=dict)
    rollback_active: bool
    timestamp: datetime

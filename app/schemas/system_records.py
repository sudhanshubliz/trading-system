from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AlertHistoryResponse(BaseModel):
    alert_id: str
    channel: str
    severity: str
    created_at: datetime
    opportunity_id: str | None = None
    strategy_family: str | None = None
    summary: str | None = None
    dry_run: bool | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class OperatorNoteResponse(BaseModel):
    note_id: str
    note_type: str
    related_entity_id: str | None = None
    created_at: datetime
    note: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class IncidentResponse(BaseModel):
    incident_id: str
    category: str | None = None
    severity: str
    source: str | None = None
    status: str
    impacted_scope: str | None = None
    created_at: datetime
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    updated_at: datetime
    title: str | None = None
    summary: str | None = None
    details: str | None = None
    related_entity_id: str | None = None
    related_provider: str | None = None
    related_strategy: str | None = None
    related_symbol_or_market: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class OperatorNoteRequest(BaseModel):
    related_entity_id: str | None = None
    note: str
    note_type: str = "operator"
    metadata: dict[str, object] = Field(default_factory=dict)


class IncidentCreateRequest(BaseModel):
    category: str
    severity: str = "medium"
    source: str = "system"
    impacted_scope: str = "system"
    title: str
    summary: str | None = None
    details: str | None = None
    related_entity_id: str | None = None
    related_provider: str | None = None
    related_strategy: str | None = None
    related_symbol_or_market: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class IncidentUpdateRequest(BaseModel):
    note: str | None = None
    severity: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AlertHistoryListResponse(BaseModel):
    items: list[AlertHistoryResponse] = Field(default_factory=list)
    count: int


class OperatorNoteListResponse(BaseModel):
    items: list[OperatorNoteResponse] = Field(default_factory=list)
    count: int


class IncidentListResponse(BaseModel):
    items: list[IncidentResponse] = Field(default_factory=list)
    count: int

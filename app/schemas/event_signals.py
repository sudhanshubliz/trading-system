from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NormalizedEventResponse(BaseModel):
    event_id: str
    source: str
    title: str
    summary: str
    category: str
    event_type: str
    event_time: datetime
    detection_time: datetime
    entities: list[str] = Field(default_factory=list)
    importance_score: float
    sentiment_score: float | None = None
    relevance_score: float
    event_window_state: str
    metadata: dict[str, object] = Field(default_factory=dict)


class EventSignalResponse(BaseModel):
    signal_id: str
    event_id: str
    symbol_or_market: str
    timestamp: datetime
    direction: str
    confidence: float
    importance: float
    timeliness_decay: float
    expected_holding_period: str
    raw_signal: dict[str, object] = Field(default_factory=dict)
    explanation: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class EventListResponse(BaseModel):
    items: list[NormalizedEventResponse] = Field(default_factory=list)
    count: int


class EventSignalListResponse(BaseModel):
    items: list[EventSignalResponse] = Field(default_factory=list)
    count: int


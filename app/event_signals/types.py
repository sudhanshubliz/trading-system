from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class NormalizedEvent:
    event_id: str
    source: str
    title: str
    summary: str
    category: str
    event_type: str
    event_time: datetime
    detection_time: datetime
    entities: list[str]
    importance_score: float
    sentiment_score: float | None
    relevance_score: float
    event_window_state: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class EventSignalCandidate:
    signal_id: str
    event_id: str
    symbol_or_market: str
    timestamp: datetime
    direction: str
    confidence: float
    importance: float
    timeliness_decay: float
    expected_holding_period: str
    raw_signal: dict[str, object]
    explanation: list[str]
    metadata: dict[str, object] = field(default_factory=dict)


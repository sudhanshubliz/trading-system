from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class RegimeSnapshot:
    snapshot_id: str
    symbol: str
    regime: str
    confidence: float
    generated_at: datetime
    trend_score: float
    volatility_score: float
    compression_score: float
    mean_reversion_score: float
    supporting_factors: list[str] = field(default_factory=list)
    veto_factors: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class WalletProfile:
    wallet_id: str
    provider: str
    first_seen: datetime
    last_seen: datetime
    market_count: int
    trade_count: int
    estimated_hit_rate: float
    estimated_pnl_score: float
    timing_score: float
    sizing_discipline_score: float
    concentration_score: float
    crowding_score: float
    persistence_score: float
    quality_score: float
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class WalletObservation:
    observation_id: str
    wallet_id: str
    provider: str
    observed_at: datetime
    market_or_symbol: str
    action: str
    inferred_direction: str
    inferred_conviction: float
    sizing_bucket: str
    latency_seconds: float | None
    associated_event: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class WalletSignal:
    signal_id: str
    wallet_id: str
    symbol_or_market: str
    timestamp: datetime
    direction: str
    confidence: float
    rationale: list[str]
    quality_score_snapshot: float
    crowding_risk: float
    recommended_action: str
    metadata: dict[str, object] = field(default_factory=dict)


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class LatencyArbOpportunity:
    opportunity_id: str
    market_id: str
    market_title: str
    symbol: str
    timestamp: datetime
    fair_probability: float
    market_probability: float
    gross_edge_bps: float
    fee_estimate_bps: float
    slippage_estimate_bps: float
    net_edge_bps: float
    confidence: float
    depth_usd: float
    spread_bps: float | None
    time_to_expiry_seconds: float
    tradable: bool
    recommended_direction: str
    explanation: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

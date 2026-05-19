from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class MarketMakingQuote:
    quote_id: str
    market_id: str
    market_title: str
    timestamp: datetime
    fair_probability: float
    quoted_bid: float
    quoted_ask: float
    spread_bps: float
    max_inventory_usd: float
    inventory_bias: float
    expected_spread_capture_bps: float
    adverse_selection_risk_bps: float
    tradable: bool
    recommended_action: str
    explanation: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

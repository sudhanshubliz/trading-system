from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class PolymarketOrderBook:
    market_id: str
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    depth_usd: float
    spread_bps: float | None
    captured_at: datetime


@dataclass(slots=True)
class PolymarketMarket:
    market_id: str
    title: str
    category: str
    event_slug: str
    status: str
    close_time: datetime | None
    last_updated_at: datetime
    yes_price: float | None
    no_price: float | None
    linked_group: str | None = None
    linked_rule: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class LinkedMarketValidation:
    validation_id: str
    rule_name: str
    related_markets: list[str]
    status: str
    deviation: float
    explanation: list[str]
    detected_at: datetime
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class PolymarketOpportunity:
    opportunity_id: str
    market_id: str
    market_title: str
    timestamp: datetime
    signal_family: str
    opportunity_type: str
    yes_price: float | None
    no_price: float | None
    yes_plus_no: float | None
    deviation_from_one: float | None
    spread: float | None
    liquidity_estimate: float | None
    stale_market: bool
    gross_edge_estimate: float
    fee_estimate: float
    slippage_estimate: float
    net_edge_estimate: float
    confidence: float
    tradable: bool
    recommended_direction: str
    expected_holding_period: str
    explanation: list[str]
    metadata: dict[str, object] = field(default_factory=dict)


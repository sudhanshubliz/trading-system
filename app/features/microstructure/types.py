from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class MicrostructureFeatureSnapshot:
    snapshot_id: str
    symbol: str
    timestamp: datetime
    top_of_book_spread_bps: float | None
    relative_spread_bps: float | None
    top_level_imbalance: float | None
    top_n_imbalance: float | None
    order_book_pressure: float | None
    microprice: float | None
    book_slope: float | None
    depth_concentration: float | None
    total_depth_usd: float | None
    depth_depletion_flag: bool
    quote_instability_score: float
    trade_flow_imbalance: float | None
    signed_volume: float | None
    trade_intensity: float | None
    burst_score: float
    realized_short_volatility: float | None
    adverse_selection_proxy: float | None
    stale_book: bool
    spread_state: str
    liquidity_state: str
    imbalance_state: str
    volatility_state: str
    market_state: str
    signal_policy: str
    confidence: float
    direction: str
    explanation: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

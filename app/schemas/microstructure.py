from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MicrostructureSnapshotResponse(BaseModel):
    snapshot_id: str
    symbol: str
    timestamp: datetime
    top_of_book_spread_bps: float | None = None
    relative_spread_bps: float | None = None
    top_level_imbalance: float | None = None
    top_n_imbalance: float | None = None
    order_book_pressure: float | None = None
    microprice: float | None = None
    book_slope: float | None = None
    depth_concentration: float | None = None
    total_depth_usd: float | None = None
    depth_depletion_flag: bool
    quote_instability_score: float
    trade_flow_imbalance: float | None = None
    signed_volume: float | None = None
    trade_intensity: float | None = None
    burst_score: float
    realized_short_volatility: float | None = None
    adverse_selection_proxy: float | None = None
    stale_book: bool
    spread_state: str
    liquidity_state: str
    imbalance_state: str
    volatility_state: str
    market_state: str
    signal_policy: str
    confidence: float
    direction: str
    explanation: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class MicrostructureSnapshotListResponse(BaseModel):
    items: list[MicrostructureSnapshotResponse] = Field(default_factory=list)
    count: int

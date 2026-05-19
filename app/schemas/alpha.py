from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TimeframeFeatureResponse(BaseModel):
    timeframe: str
    latest_close: float
    previous_close: float | None = None
    rsi: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    sma_fast: float | None = None
    sma_slow: float | None = None
    ema_gap_bps: float | None = None
    ema_slope_bps: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    atr: float | None = None
    atr_pct: float | None = None
    vwap: float | None = None
    breakout_up_distance_pct: float | None = None
    breakout_down_distance_pct: float | None = None
    breakout_bias: float
    donchian_upper: float | None = None
    donchian_lower: float | None = None
    donchian_mid: float | None = None
    range_compression_pct: float | None = None
    bollinger_upper: float | None = None
    bollinger_mid: float | None = None
    bollinger_lower: float | None = None
    bollinger_width_pct: float | None = None
    keltner_upper: float | None = None
    keltner_mid: float | None = None
    keltner_lower: float | None = None
    keltner_width_pct: float | None = None
    squeeze_on: bool = False
    volume_ratio: float | None = None
    return_1_pct: float | None = None
    return_3_pct: float | None = None
    vwap_gap_bps: float | None = None
    market_structure: str = "undetermined"
    order_block_hint: str = "research_placeholder_none"
    fvg_hint: str = "research_placeholder_none"
    trend_state: str


class AlphaFeatureResponse(BaseModel):
    symbol: str
    generated_at: datetime
    source: str
    trend_timeframe: str
    setup_timeframe: str
    trigger_timeframe: str
    market_price: float | None = None
    feature_coverage: float
    bullish_timeframes: list[str] = Field(default_factory=list)
    bearish_timeframes: list[str] = Field(default_factory=list)
    timeframes: dict[str, TimeframeFeatureResponse] = Field(default_factory=dict)


class FusionComponentResponse(BaseModel):
    name: str
    score: float
    weight: float
    contribution: float
    state: str
    explanation: str


class FusedAlphaSignalResponse(BaseModel):
    signal_id: str
    symbol: str
    score: float
    direction: str
    confidence: float
    confidence_band: str = "medium"
    strategy_family: str = "technical_features"
    explanation: list[str] = Field(default_factory=list)
    supporting_factors: list[str] = Field(default_factory=list)
    veto_factors: list[str] = Field(default_factory=list)
    components: list[FusionComponentResponse] = Field(default_factory=list)
    feature_snapshot: AlphaFeatureResponse
    generated_at: datetime
    status: str
    regime: str | None = None
    tradable: bool = True
    expected_holding_period: str = "intra-day"
    source_breakdown: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class AlphaSourceReadingResponse(BaseModel):
    reading_id: str
    source_name: str
    symbol_or_market: str
    direction: str
    confidence: float
    expected_holding_period: str
    strategy_family: str
    raw_signal: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    timestamp: datetime


class AlphaFusionEvaluateRequest(BaseModel):
    symbols: list[str] | None = None
    markets: list[str] | None = None
    targets: list[str] | None = None


class FusedAlphaSignalListResponse(BaseModel):
    items: list[FusedAlphaSignalResponse] = Field(default_factory=list)
    count: int


class AlphaSourceReadingListResponse(BaseModel):
    items: list[AlphaSourceReadingResponse] = Field(default_factory=list)
    count: int

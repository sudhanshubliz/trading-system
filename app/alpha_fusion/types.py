from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class TimeframeFeatureVector:
    timeframe: str
    latest_close: float
    previous_close: float | None
    rsi: float | None
    ema_fast: float | None
    ema_slow: float | None
    ema_gap_bps: float | None
    ema_slope_bps: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    atr: float | None
    atr_pct: float | None
    breakout_up_distance_pct: float | None
    breakout_down_distance_pct: float | None
    breakout_bias: float
    volume_ratio: float | None
    return_1_pct: float | None
    return_3_pct: float | None
    vwap_gap_bps: float | None
    trend_state: str
    sma_fast: float | None = None
    sma_slow: float | None = None
    vwap: float | None = None
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
    market_structure: str = "undetermined"
    order_block_hint: str = "research_placeholder_none"
    fvg_hint: str = "research_placeholder_none"


@dataclass(slots=True)
class AlphaFeatureSnapshot:
    symbol: str
    generated_at: datetime
    source: str
    trend_timeframe: str
    setup_timeframe: str
    trigger_timeframe: str
    market_price: float | None
    feature_coverage: float
    bullish_timeframes: list[str] = field(default_factory=list)
    bearish_timeframes: list[str] = field(default_factory=list)
    timeframes: dict[str, TimeframeFeatureVector] = field(default_factory=dict)


@dataclass(slots=True)
class FusionComponent:
    name: str
    score: float
    weight: float
    contribution: float
    state: str
    explanation: str


@dataclass(slots=True)
class FusedAlphaSignal:
    signal_id: str
    symbol: str
    score: float
    direction: str
    confidence: float
    explanation: list[str]
    supporting_factors: list[str]
    veto_factors: list[str]
    components: list[FusionComponent]
    feature_snapshot: AlphaFeatureSnapshot
    generated_at: datetime
    confidence_band: str = "medium"
    strategy_family: str = "technical_features"
    status: str = "candidate"
    regime: str | None = None
    tradable: bool = True
    expected_holding_period: str = "intra-day"
    source_breakdown: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class AlphaSourceReading:
    reading_id: str
    source_name: str
    symbol_or_market: str
    direction: str
    confidence: float
    expected_holding_period: str
    strategy_family: str
    raw_signal: dict[str, object]
    metadata: dict[str, object]
    timestamp: datetime

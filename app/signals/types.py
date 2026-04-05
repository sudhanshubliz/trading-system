from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class TimeframeIndicatorSnapshot:
    ema_fast: float | None
    ema_slow: float | None
    rsi: float | None
    vwap: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    latest_close: float | None
    previous_close: float | None
    latest_volume: float | None
    average_volume: float | None
    average_range_pct: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "rsi": self.rsi,
            "vwap": self.vwap,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_hist": self.macd_hist,
            "latest_close": self.latest_close,
            "previous_close": self.previous_close,
            "latest_volume": self.latest_volume,
            "average_volume": self.average_volume,
            "average_range_pct": self.average_range_pct,
        }


@dataclass(slots=True)
class IndicatorSnapshot:
    timeframes: dict[str, TimeframeIndicatorSnapshot] = field(default_factory=dict)

    def as_dict(self) -> dict[str, dict[str, float | None]]:
        return {timeframe: snapshot.as_dict() for timeframe, snapshot in self.timeframes.items()}


@dataclass(slots=True)
class CandidateSignal:
    signal_id: str
    symbol: str
    side: str
    strategy_name: str
    confidence_score: int
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    reward_risk_ratio: float
    rationale: list[str]
    indicators_snapshot: dict[str, dict[str, float | None]]
    generated_at: datetime
    status: str = "candidate"


@dataclass(slots=True)
class SignalEvaluationResult:
    items: list[CandidateSignal]
    count: int

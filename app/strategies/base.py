from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from app.config.settings import Settings
from app.market_data.types import Candle
from app.signals.types import CandidateSignal, IndicatorSnapshot


@dataclass(slots=True)
class StrategyContext:
    symbol: str
    regime_candles: list[Candle]
    setup_candles: list[Candle]
    trigger_candles: list[Candle]
    indicators: IndicatorSnapshot
    settings: Settings
    generated_at: datetime
    signal_id_factory: Callable[[str, str, str, datetime], str]


class SignalStrategy(Protocol):
    name: str

    def evaluate(self, context: StrategyContext) -> CandidateSignal | None:
        ...


def recent_swing_low(candles: list[Candle], lookback: int) -> float | None:
    if len(candles) < lookback:
        return None
    return min(candle.low for candle in candles[-lookback:])


def recent_swing_high(candles: list[Candle], lookback: int) -> float | None:
    if len(candles) < lookback:
        return None
    return max(candle.high for candle in candles[-lookback:])


def recent_range_high(candles: list[Candle], lookback: int, *, exclude_latest: bool = True) -> float | None:
    if exclude_latest:
        source = candles[:-1]
    else:
        source = candles
    if len(source) < lookback:
        return None
    return max(candle.high for candle in source[-lookback:])


def recent_range_low(candles: list[Candle], lookback: int, *, exclude_latest: bool = True) -> float | None:
    if exclude_latest:
        source = candles[:-1]
    else:
        source = candles
    if len(source) < lookback:
        return None
    return min(candle.low for candle in source[-lookback:])


def recent_average_volume(candles: list[Candle], lookback: int, *, exclude_latest: bool = True) -> float | None:
    if exclude_latest:
        source = candles[:-1]
    else:
        source = candles
    if len(source) < lookback:
        return None
    selected = source[-lookback:]
    return sum(candle.volume for candle in selected) / len(selected)


def recent_average_range_percent(candles: list[Candle], lookback: int) -> float | None:
    if len(candles) < lookback:
        return None

    total = 0.0
    count = 0
    for candle in candles[-lookback:]:
        if candle.close <= 0:
            continue
        total += ((candle.high - candle.low) / candle.close) * 100
        count += 1

    if count == 0:
        return None

    return total / count

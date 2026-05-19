from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean, pstdev

from app.alpha_fusion.types import AlphaFeatureSnapshot, TimeframeFeatureVector
from app.config.settings import Settings, get_settings
from app.indicators.atr import calculate_atr
from app.indicators.ema import calculate_ema
from app.indicators.macd import calculate_macd
from app.indicators.rsi import calculate_rsi
from app.indicators.vwap import calculate_vwap
from app.market_data.types import Candle


def _safe_bps_delta(current: float | None, base: float | None) -> float | None:
    if current is None or base in (None, 0):
        return None
    return round(((current - base) / base) * 10000, 4)


def _safe_pct_delta(current: float | None, base: float | None) -> float | None:
    if current is None or base in (None, 0):
        return None
    return round(((current - base) / base) * 100, 6)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _simple_moving_average(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        return [None for _ in values]
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < period:
            result.append(None)
            continue
        window = values[index - period + 1 : index + 1]
        result.append(sum(window) / period)
    return result


@dataclass(slots=True)
class BreakoutWindow:
    upper_distance_pct: float | None
    lower_distance_pct: float | None
    bias: float
    upper: float | None
    lower: float | None
    mid: float | None
    width_pct: float | None


@dataclass(slots=True)
class VolatilityChannel:
    upper: float | None
    mid: float | None
    lower: float | None
    width_pct: float | None


class TradingViewLikeFeatureEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def build_snapshot(
        self,
        *,
        symbol: str,
        candles_by_timeframe: dict[str, list[Candle]],
        generated_at: datetime,
        market_price: float | None = None,
    ) -> AlphaFeatureSnapshot | None:
        timeframes: dict[str, TimeframeFeatureVector] = {}
        bullish_timeframes: list[str] = []
        bearish_timeframes: list[str] = []

        for timeframe in self.settings.alpha_feature_timeframes:
            candles = candles_by_timeframe.get(timeframe)
            if not candles:
                continue
            vector = self._build_timeframe_vector(timeframe=timeframe, candles=candles)
            if vector is None:
                continue
            timeframes[timeframe] = vector
            if vector.trend_state == "bullish":
                bullish_timeframes.append(timeframe)
            elif vector.trend_state == "bearish":
                bearish_timeframes.append(timeframe)

        if not timeframes:
            return None

        coverage = round(len(timeframes) / max(len(self.settings.alpha_feature_timeframes), 1), 4)
        return AlphaFeatureSnapshot(
            symbol=symbol,
            generated_at=generated_at,
            source="tradingview_like",
            trend_timeframe=self.settings.signals_regime_timeframe,
            setup_timeframe=self.settings.signals_setup_timeframe,
            trigger_timeframe=self.settings.signals_trigger_timeframe,
            market_price=_round(market_price),
            feature_coverage=coverage,
            bullish_timeframes=bullish_timeframes,
            bearish_timeframes=bearish_timeframes,
            timeframes=timeframes,
        )

    def _build_timeframe_vector(
        self,
        *,
        timeframe: str,
        candles: list[Candle],
    ) -> TimeframeFeatureVector | None:
        closes = [candle.close for candle in candles]
        highs = [candle.high for candle in candles]
        lows = [candle.low for candle in candles]
        volumes = [candle.volume for candle in candles]
        if len(closes) < 2:
            return None

        ema_fast_series = calculate_ema(closes, self.settings.ema_fast_period)
        ema_slow_series = calculate_ema(closes, self.settings.ema_slow_period)
        sma_fast_series = _simple_moving_average(closes, self.settings.ema_fast_period)
        sma_slow_series = _simple_moving_average(closes, self.settings.ema_slow_period)
        rsi_series = calculate_rsi(closes, self.settings.rsi_period)
        vwap_series = calculate_vwap(highs, lows, closes, volumes)
        atr_series = calculate_atr(highs, lows, closes, self.settings.alpha_atr_period)
        macd_line, macd_signal, macd_hist = calculate_macd(
            closes,
            self.settings.macd_fast_period,
            self.settings.macd_slow_period,
            self.settings.macd_signal_period,
        )

        latest_close = closes[-1]
        ema_fast = ema_fast_series[-1]
        ema_slow = ema_slow_series[-1]
        previous_ema_fast = next((item for item in reversed(ema_fast_series[:-1]) if item is not None), None)
        breakout = self._build_breakout_window(candles)
        bollinger = self._build_bollinger_channel(closes)
        keltner = self._build_keltner_channel(closes, atr_series)
        squeeze_on = bool(
            bollinger.upper is not None
            and keltner.upper is not None
            and bollinger.lower is not None
            and keltner.lower is not None
            and bollinger.upper <= keltner.upper
            and bollinger.lower >= keltner.lower
        )

        average_volume = _average(volumes[-self.settings.volume_lookback :])
        volume_ratio = None
        if average_volume not in (None, 0):
            volume_ratio = _round(volumes[-1] / average_volume)

        trend_state = "neutral"
        if ema_fast is not None and ema_slow is not None:
            if ema_fast > ema_slow and latest_close >= ema_fast:
                trend_state = "bullish"
            elif ema_fast < ema_slow and latest_close <= ema_fast:
                trend_state = "bearish"

        return TimeframeFeatureVector(
            timeframe=timeframe,
            latest_close=_round(latest_close) or latest_close,
            previous_close=_round(closes[-2]),
            rsi=_round(rsi_series[-1]),
            ema_fast=_round(ema_fast),
            ema_slow=_round(ema_slow),
            sma_fast=_round(sma_fast_series[-1]),
            sma_slow=_round(sma_slow_series[-1]),
            ema_gap_bps=_safe_bps_delta(ema_fast, ema_slow),
            ema_slope_bps=_safe_bps_delta(ema_fast, previous_ema_fast),
            macd=_round(macd_line[-1]),
            macd_signal=_round(macd_signal[-1]),
            macd_hist=_round(macd_hist[-1]),
            atr=_round(atr_series[-1]),
            atr_pct=_safe_pct_delta(atr_series[-1], latest_close),
            vwap=_round(vwap_series[-1] if vwap_series else None),
            breakout_up_distance_pct=breakout.upper_distance_pct,
            breakout_down_distance_pct=breakout.lower_distance_pct,
            breakout_bias=breakout.bias,
            donchian_upper=_round(breakout.upper),
            donchian_lower=_round(breakout.lower),
            donchian_mid=_round(breakout.mid),
            range_compression_pct=_round(breakout.width_pct),
            bollinger_upper=_round(bollinger.upper),
            bollinger_mid=_round(bollinger.mid),
            bollinger_lower=_round(bollinger.lower),
            bollinger_width_pct=_round(bollinger.width_pct),
            keltner_upper=_round(keltner.upper),
            keltner_mid=_round(keltner.mid),
            keltner_lower=_round(keltner.lower),
            keltner_width_pct=_round(keltner.width_pct),
            squeeze_on=squeeze_on,
            volume_ratio=volume_ratio,
            return_1_pct=_safe_pct_delta(latest_close, closes[-2]),
            return_3_pct=_safe_pct_delta(latest_close, closes[-4]) if len(closes) >= 4 else None,
            vwap_gap_bps=_safe_bps_delta(latest_close, vwap_series[-1] if vwap_series else None),
            market_structure=self._classify_market_structure(candles),
            order_block_hint=self._detect_order_block_hint(candles),
            fvg_hint=self._detect_fvg_hint(candles),
            trend_state=trend_state,
        )

    def _build_breakout_window(self, candles: list[Candle]) -> BreakoutWindow:
        if len(candles) <= self.settings.breakout_lookback:
            return BreakoutWindow(None, None, 0.0, None, None, None, None)

        latest_close = candles[-1].close
        if latest_close == 0:
            return BreakoutWindow(None, None, 0.0, None, None, None, None)

        lookback_window = candles[-(self.settings.breakout_lookback + 1) : -1]
        upper = max(candle.high for candle in lookback_window)
        lower = min(candle.low for candle in lookback_window)
        upper_distance = round(((upper - latest_close) / latest_close) * 100, 6)
        lower_distance = round(((latest_close - lower) / latest_close) * 100, 6)
        width_pct = round(((upper - lower) / latest_close) * 100, 6)
        mid = (upper + lower) / 2

        bias = 0.0
        if latest_close > upper:
            bias = 1.0
        elif latest_close < lower:
            bias = -1.0
        else:
            range_width = max(upper - lower, 1e-9)
            relative_position = ((latest_close - lower) / range_width) * 2 - 1
            bias = round(max(min(relative_position, 1.0), -1.0), 6)

        return BreakoutWindow(upper_distance, lower_distance, bias, upper, lower, mid, width_pct)

    def _build_bollinger_channel(self, closes: list[float]) -> VolatilityChannel:
        period = self.settings.feature_bollinger_period
        if len(closes) < period or period <= 1:
            return VolatilityChannel(None, None, None, None)
        window = closes[-period:]
        mid = mean(window)
        deviation = pstdev(window)
        width = self.settings.feature_bollinger_stddev * deviation
        upper = mid + width
        lower = mid - width
        width_pct = ((upper - lower) / max(closes[-1], 1e-9)) * 100
        return VolatilityChannel(upper, mid, lower, width_pct)

    def _build_keltner_channel(self, closes: list[float], atr_series: list[float | None]) -> VolatilityChannel:
        period = self.settings.feature_keltner_period
        if len(closes) < period:
            return VolatilityChannel(None, None, None, None)
        ema_mid = calculate_ema(closes, period)[-1]
        atr_value = atr_series[-1]
        if ema_mid is None or atr_value is None:
            return VolatilityChannel(None, None, None, None)
        upper = ema_mid + (atr_value * self.settings.feature_keltner_atr_mult)
        lower = ema_mid - (atr_value * self.settings.feature_keltner_atr_mult)
        width_pct = ((upper - lower) / max(closes[-1], 1e-9)) * 100
        return VolatilityChannel(upper, ema_mid, lower, width_pct)

    def _classify_market_structure(self, candles: list[Candle]) -> str:
        lookback = self.settings.feature_market_structure_lookback
        if len(candles) < lookback + 2:
            return "undetermined"
        window = candles[-lookback:]
        first_half = window[: len(window) // 2]
        second_half = window[len(window) // 2 :]
        if not first_half or not second_half:
            return "undetermined"

        first_high = max(candle.high for candle in first_half)
        second_high = max(candle.high for candle in second_half)
        first_low = min(candle.low for candle in first_half)
        second_low = min(candle.low for candle in second_half)

        if second_high > first_high and second_low > first_low:
            return "higher_highs_higher_lows"
        if second_high < first_high and second_low < first_low:
            return "lower_highs_lower_lows"
        if second_high > first_high and second_low <= first_low:
            return "expanding"
        if second_high <= first_high and second_low > first_low:
            return "compressing"
        return "balanced"

    def _detect_order_block_hint(self, candles: list[Candle]) -> str:
        if len(candles) < 4:
            return "research_placeholder_none"
        recent = candles[-4:]
        body_changes = [candle.close - candle.open for candle in recent]
        if body_changes[-2] < 0 and body_changes[-1] > abs(body_changes[-2]) * 0.9:
            return "research_placeholder_bullish"
        if body_changes[-2] > 0 and body_changes[-1] < -abs(body_changes[-2]) * 0.9:
            return "research_placeholder_bearish"
        return "research_placeholder_none"

    def _detect_fvg_hint(self, candles: list[Candle]) -> str:
        if len(candles) < 3:
            return "research_placeholder_none"
        a, _, c = candles[-3:]
        if c.low > a.high:
            return "research_placeholder_bullish_gap"
        if c.high < a.low:
            return "research_placeholder_bearish_gap"
        return "research_placeholder_none"

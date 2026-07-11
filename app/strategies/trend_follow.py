from __future__ import annotations

from app.signals.types import CandidateSignal
from app.strategies.base import (
    SignalStrategy,
    StrategyContext,
    recent_average_range_percent,
    recent_swing_high,
    recent_swing_low,
)
from app.strategies.scorer import score_signal


class TrendFollowContinuationStrategy(SignalStrategy):
    name = "trend_follow_continuation"

    def evaluate(self, context: StrategyContext) -> CandidateSignal | None:
        regime = context.indicators.timeframes[context.settings.signals_regime_timeframe]
        setup = context.indicators.timeframes[context.settings.signals_setup_timeframe]
        trigger = context.indicators.timeframes[context.settings.signals_trigger_timeframe]

        if regime.ema_fast is None or regime.ema_slow is None:
            return None
        if setup.ema_fast is None or setup.vwap is None:
            return None
        if trigger.macd_hist is None or trigger.rsi is None or trigger.latest_close is None:
            return None
        if trigger.previous_close is None:
            return None

        is_bullish_regime = regime.ema_fast > regime.ema_slow
        is_bearish_regime = regime.ema_fast < regime.ema_slow
        if not is_bullish_regime and not is_bearish_regime:
            return None

        setup_close = setup.latest_close
        if setup_close is None or setup_close <= 0:
            return None

        distance_to_ema = abs(setup_close - setup.ema_fast) / setup_close
        distance_to_vwap = abs(setup_close - setup.vwap) / setup_close
        regime_gap_pct = abs(regime.ema_fast - regime.ema_slow) / setup_close
        if not self._pullback_is_valid(
            distance_to_ema=distance_to_ema,
            distance_to_vwap=distance_to_vwap,
            regime_gap_pct=regime_gap_pct,
            context=context,
        ):
            return None

        trigger_hist = trigger.macd_hist
        latest_close = trigger.latest_close
        average_range_pct = recent_average_range_percent(context.trigger_candles, 20)
        if average_range_pct is None or average_range_pct < context.settings.signals_min_trigger_range_pct:
            return None
        trigger_candle = context.trigger_candles[-1]
        trigger_body_pct = abs(trigger_candle.close - trigger_candle.open) / latest_close * 100
        is_green_trigger = trigger_candle.close >= trigger_candle.open
        is_red_trigger = trigger_candle.close <= trigger_candle.open

        if is_bullish_regime:
            if not is_green_trigger and not self._allow_countertrend_trigger(
                side="long",
                trigger_body_pct=trigger_body_pct,
                average_range_pct=average_range_pct,
                trigger_hist=trigger_hist,
                trigger_rsi=trigger.rsi,
                regime_gap_pct=regime_gap_pct,
                context=context,
            ):
                return None
            if trigger_hist < 0:
                return None
            if (
                trigger.rsi <= context.settings.signals_rsi_long_min
                or trigger.rsi >= context.settings.signals_rsi_long_max
            ):
                return None

            stop_loss = recent_swing_low(context.trigger_candles, 10)
            if stop_loss is None or stop_loss >= latest_close:
                return None

            risk = latest_close - stop_loss
            if risk <= 0:
                return None

            target_1 = latest_close + (1.5 * risk)
            target_2 = latest_close + (2.5 * risk)
            reward_risk_ratio = (target_1 - latest_close) / risk
            if reward_risk_ratio < 1.2:
                return None

            rationale = [
                "1h bullish trend confirmed by EMA alignment",
                "15m pullback is near fast EMA and VWAP support",
                "5m trigger shows positive momentum with RSI above neutral",
            ]
            if distance_to_vwap > context.settings.signals_pullback_tolerance_pct:
                rationale.append("15m VWAP is lagging the trend, but fast EMA support and regime strength still anchor the pullback")
            if not is_green_trigger:
                rationale.append("5m trigger candle is shallow and counter-color, but continuation strength remains intact")
            side = "long"
        else:
            if not is_red_trigger and not self._allow_countertrend_trigger(
                side="short",
                trigger_body_pct=trigger_body_pct,
                average_range_pct=average_range_pct,
                trigger_hist=trigger_hist,
                trigger_rsi=trigger.rsi,
                regime_gap_pct=regime_gap_pct,
                context=context,
            ):
                return None
            if trigger_hist > 0:
                return None
            if (
                trigger.rsi <= context.settings.signals_rsi_short_min
                or trigger.rsi >= context.settings.signals_rsi_short_max
            ):
                return None

            stop_loss = recent_swing_high(context.trigger_candles, 10)
            if stop_loss is None or stop_loss <= latest_close:
                return None

            risk = stop_loss - latest_close
            if risk <= 0:
                return None

            target_1 = latest_close - (1.5 * risk)
            target_2 = latest_close - (2.5 * risk)
            reward_risk_ratio = (latest_close - target_1) / risk
            if reward_risk_ratio < 1.2:
                return None

            rationale = [
                "1h bearish trend confirmed by EMA alignment",
                "15m rebound is near fast EMA and VWAP resistance",
                "5m trigger shows negative momentum with RSI below neutral",
            ]
            if distance_to_vwap > context.settings.signals_pullback_tolerance_pct:
                rationale.append("15m VWAP is lagging the trend, but fast EMA resistance and regime strength still anchor the rebound")
            if not is_red_trigger:
                rationale.append("5m trigger candle is shallow and counter-color, but continuation strength remains intact")
            side = "short"

        confidence_score = score_signal(
            trend_alignment=1.0,
            momentum=0.85,
            volume_confirmation=0.55,
            structure_quality=0.80,
        )
        if confidence_score < 60:
            return None

        return CandidateSignal(
            signal_id=context.signal_id_factory(context.symbol, self.name, side, context.generated_at),
            symbol=context.symbol,
            side=side,
            strategy_name=self.name,
            confidence_score=confidence_score,
            entry_price=latest_close,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            reward_risk_ratio=round(reward_risk_ratio, 2),
            rationale=rationale,
            indicators_snapshot=context.indicators.as_dict(),
            generated_at=context.generated_at,
            status="candidate",
        )

    def _allow_countertrend_trigger(
        self,
        *,
        side: str,
        trigger_body_pct: float,
        average_range_pct: float,
        trigger_hist: float,
        trigger_rsi: float,
        regime_gap_pct: float,
        context: StrategyContext,
    ) -> bool:
        if average_range_pct <= 0:
            return False

        body_is_shallow = (
            trigger_body_pct
            <= average_range_pct * context.settings.signals_countertrend_trigger_body_to_range_ratio
        )
        regime_is_strong = regime_gap_pct >= context.settings.signals_countertrend_trigger_min_regime_gap_pct
        rsi_buffer = context.settings.signals_countertrend_trigger_rsi_buffer

        if side == "long":
            return (
                body_is_shallow
                and regime_is_strong
                and trigger_hist > 0
                and trigger_rsi >= context.settings.signals_rsi_long_min + rsi_buffer
            )

        return (
            body_is_shallow
            and regime_is_strong
            and trigger_hist < 0
            and trigger_rsi <= context.settings.signals_rsi_short_max - rsi_buffer
        )

    def _pullback_is_valid(
        self,
        *,
        distance_to_ema: float,
        distance_to_vwap: float,
        regime_gap_pct: float,
        context: StrategyContext,
    ) -> bool:
        base_tolerance = context.settings.signals_pullback_tolerance_pct
        if distance_to_ema <= base_tolerance and distance_to_vwap <= base_tolerance:
            return True

        strong_regime = regime_gap_pct >= context.settings.signals_trend_pullback_strong_regime_gap_pct
        relaxed_vwap_tolerance = base_tolerance + context.settings.signals_trend_pullback_vwap_slack_pct

        return (
            strong_regime
            and distance_to_ema <= base_tolerance
            and distance_to_vwap <= relaxed_vwap_tolerance
        )

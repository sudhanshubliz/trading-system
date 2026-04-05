from __future__ import annotations

from app.signals.types import CandidateSignal
from app.strategies.base import SignalStrategy, StrategyContext, recent_average_range_percent, recent_swing_low
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

        if regime.ema_fast <= regime.ema_slow:
            return None

        setup_close = setup.latest_close
        if setup_close is None or setup_close <= 0:
            return None

        distance_to_ema = abs(setup_close - setup.ema_fast) / setup_close
        distance_to_vwap = abs(setup_close - setup.vwap) / setup_close
        if distance_to_ema > 0.006 or distance_to_vwap > 0.006:
            return None

        trigger_hist = trigger.macd_hist
        latest_close = trigger.latest_close
        if latest_close <= trigger.previous_close:
            return None
        if trigger_hist < 0:
            return None
        if trigger.rsi <= 50 or trigger.rsi >= 72:
            return None

        average_range_pct = recent_average_range_percent(context.trigger_candles, 20)
        if average_range_pct is None or average_range_pct < 0.2:
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

        confidence_score = score_signal(
            trend_alignment=1.0,
            momentum=0.85,
            volume_confirmation=0.55,
            structure_quality=0.80,
        )
        if confidence_score < 60:
            return None

        return CandidateSignal(
            signal_id=context.signal_id_factory(context.symbol, self.name, "long", context.generated_at),
            symbol=context.symbol,
            side="long",
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

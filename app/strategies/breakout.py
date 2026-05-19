from __future__ import annotations

from app.signals.types import CandidateSignal
from app.strategies.base import (
    SignalStrategy,
    StrategyContext,
    recent_average_range_percent,
    recent_average_volume,
    recent_range_low,
    recent_range_high,
    recent_swing_high,
    recent_swing_low,
)
from app.strategies.scorer import score_signal


class BreakoutConfirmationStrategy(SignalStrategy):
    name = "breakout_confirmation"

    def evaluate(self, context: StrategyContext) -> CandidateSignal | None:
        regime = context.indicators.timeframes[context.settings.signals_regime_timeframe]
        setup = context.indicators.timeframes[context.settings.signals_setup_timeframe]
        trigger = context.indicators.timeframes[context.settings.signals_trigger_timeframe]

        if regime.ema_fast is None or regime.ema_slow is None:
            return None
        if setup.latest_close is None or trigger.latest_close is None or trigger.previous_close is None:
            return None
        if trigger.macd_hist is None or trigger.latest_volume is None:
            return None

        is_bullish_regime = regime.ema_fast > regime.ema_slow
        is_bearish_regime = regime.ema_fast < regime.ema_slow
        if not is_bullish_regime and not is_bearish_regime:
            return None

        average_volume = recent_average_volume(
            context.trigger_candles,
            context.settings.volume_lookback,
            exclude_latest=True,
        )
        if average_volume is None or average_volume <= 0:
            return None
        if trigger.latest_volume <= average_volume:
            return None

        average_range_pct = recent_average_range_percent(context.trigger_candles, 20)
        if average_range_pct is None or average_range_pct < context.settings.signals_min_trigger_range_pct:
            return None

        entry_price = trigger.latest_close
        volume_confirmation = min(trigger.latest_volume / average_volume, 2.0) / 2.0
        confidence_score = score_signal(
            trend_alignment=1.0,
            momentum=0.80,
            volume_confirmation=volume_confirmation,
            structure_quality=0.85,
        )
        if confidence_score < 60:
            return None

        breakout_buffer = 1.0 - context.settings.signals_breakout_buffer_pct
        breakdown_buffer = 1.0 + context.settings.signals_breakout_buffer_pct

        if is_bullish_regime:
            range_high = recent_range_high(
                context.setup_candles,
                context.settings.breakout_lookback,
                exclude_latest=True,
            )
            if range_high is None:
                return None
            if setup.latest_close < range_high * breakout_buffer:
                return None
            if trigger.latest_close <= trigger.previous_close:
                return None
            if trigger.macd_hist < 0:
                return None

            swing_low = recent_swing_low(context.trigger_candles, 10)
            breakout_floor = range_high * (1.0 - (context.settings.signals_breakout_buffer_pct * 2))
            stop_loss_candidates = [value for value in [swing_low, breakout_floor] if value is not None]
            if not stop_loss_candidates:
                return None
            stop_loss = max(stop_loss_candidates)
            if stop_loss >= entry_price:
                return None

            risk = entry_price - stop_loss
            if risk <= 0:
                return None
            target_1 = entry_price + (1.5 * risk)
            target_2 = entry_price + (3.0 * risk)
            reward_risk_ratio = (target_1 - entry_price) / risk
            if reward_risk_ratio < 1.2:
                return None

            rationale = [
                "1h bullish trend confirmed by EMA alignment",
                f"15m price is breaking above recent range high near {range_high:.2f}",
                "5m trigger confirms the breakout with strong close and higher volume",
            ]
            side = "long"
        else:
            range_low = recent_range_low(
                context.setup_candles,
                context.settings.breakout_lookback,
                exclude_latest=True,
            )
            if range_low is None:
                return None
            if setup.latest_close > range_low * breakdown_buffer:
                return None
            if trigger.latest_close >= trigger.previous_close:
                return None
            if trigger.macd_hist > 0:
                return None

            swing_high = recent_swing_high(context.trigger_candles, 10)
            breakdown_ceiling = range_low * (1.0 + (context.settings.signals_breakout_buffer_pct * 2))
            stop_loss_candidates = [value for value in [swing_high, breakdown_ceiling] if value is not None]
            if not stop_loss_candidates:
                return None
            stop_loss = min(stop_loss_candidates)
            if stop_loss <= entry_price:
                return None

            risk = stop_loss - entry_price
            if risk <= 0:
                return None
            target_1 = entry_price - (1.5 * risk)
            target_2 = entry_price - (3.0 * risk)
            reward_risk_ratio = (entry_price - target_1) / risk
            if reward_risk_ratio < 1.2:
                return None

            rationale = [
                "1h bearish trend confirmed by EMA alignment",
                f"15m price is breaking below recent range low near {range_low:.2f}",
                "5m trigger confirms the breakdown with strong sell volume",
            ]
            side = "short"

        return CandidateSignal(
            signal_id=context.signal_id_factory(context.symbol, self.name, side, context.generated_at),
            symbol=context.symbol,
            side=side,
            strategy_name=self.name,
            confidence_score=confidence_score,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            reward_risk_ratio=round(reward_risk_ratio, 2),
            rationale=rationale,
            indicators_snapshot=context.indicators.as_dict(),
            generated_at=context.generated_at,
            status="candidate",
        )

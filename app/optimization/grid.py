from __future__ import annotations

from itertools import product

from app.optimization.types import OptimizationCandidateConfig, OptimizationParameterGrid


def build_parameter_grid(
    grid: OptimizationParameterGrid,
    max_combinations: int,
) -> list[OptimizationCandidateConfig]:
    if max_combinations <= 0:
        return []

    ema_fast_periods = sorted(set(grid.ema_fast_periods))
    ema_slow_periods = sorted(set(grid.ema_slow_periods))
    rsi_periods = sorted(set(grid.rsi_periods))
    breakout_lookbacks = sorted(set(grid.breakout_lookbacks))
    min_confidence_scores = sorted(set(grid.min_confidence_scores))
    min_reward_risk_ratios = sorted(set(grid.min_reward_risk_ratios))

    if not all(
        [
            ema_fast_periods,
            ema_slow_periods,
            rsi_periods,
            breakout_lookbacks,
            min_confidence_scores,
            min_reward_risk_ratios,
        ]
    ):
        return []

    combinations: list[OptimizationCandidateConfig] = []
    for values in product(
        ema_fast_periods,
        ema_slow_periods,
        rsi_periods,
        breakout_lookbacks,
        min_confidence_scores,
        min_reward_risk_ratios,
    ):
        ema_fast_period, ema_slow_period, rsi_period, breakout_lookback, min_confidence_score, min_reward_risk_ratio = values
        if ema_fast_period >= ema_slow_period:
            continue
        if min_reward_risk_ratio <= 0:
            continue
        if not 0 <= min_confidence_score <= 100:
            continue
        if breakout_lookback <= 1 or rsi_period <= 1:
            continue

        combinations.append(
            OptimizationCandidateConfig(
                config_id=f"cfg_{len(combinations) + 1:04d}",
                ema_fast_period=ema_fast_period,
                ema_slow_period=ema_slow_period,
                rsi_period=rsi_period,
                breakout_lookback=breakout_lookback,
                min_confidence_score=min_confidence_score,
                min_reward_risk_ratio=float(min_reward_risk_ratio),
            )
        )
        if len(combinations) >= max_combinations:
            break

    return combinations

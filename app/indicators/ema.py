from __future__ import annotations


def calculate_ema(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        return [None] * len(values)
    if len(values) < period:
        return [None] * len(values)

    result: list[float | None] = [None] * len(values)
    initial_sma = sum(values[:period]) / period
    result[period - 1] = initial_sma

    multiplier = 2 / (period + 1)
    previous_ema = initial_sma

    for index in range(period, len(values)):
        current_ema = ((values[index] - previous_ema) * multiplier) + previous_ema
        result[index] = current_ema
        previous_ema = current_ema

    return result

from __future__ import annotations


def calculate_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    length = min(len(highs), len(lows), len(closes))
    if period <= 0 or length == 0:
        return [None] * length

    true_ranges: list[float] = []
    for index in range(length):
        high = highs[index]
        low = lows[index]
        if index == 0:
            true_ranges.append(high - low)
            continue

        previous_close = closes[index - 1]
        true_ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )

    if length < period:
        return [None] * length

    result: list[float | None] = [None] * length
    atr = sum(true_ranges[:period]) / period
    result[period - 1] = atr

    for index in range(period, length):
        atr = ((atr * (period - 1)) + true_ranges[index]) / period
        result[index] = atr

    return result

from __future__ import annotations

from app.indicators.ema import calculate_ema


def calculate_macd(
    values: list[float],
    fast_period: int,
    slow_period: int,
    signal_period: int,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    length = len(values)
    if length == 0:
        return [], [], []

    fast_ema = calculate_ema(values, fast_period)
    slow_ema = calculate_ema(values, slow_period)

    macd_line: list[float | None] = [None] * length
    compact_macd: list[float] = []
    compact_indices: list[int] = []

    for index, (fast_value, slow_value) in enumerate(zip(fast_ema, slow_ema, strict=False)):
        if fast_value is None or slow_value is None:
            continue
        macd_value = fast_value - slow_value
        macd_line[index] = macd_value
        compact_macd.append(macd_value)
        compact_indices.append(index)

    compact_signal = calculate_ema(compact_macd, signal_period)
    signal_line: list[float | None] = [None] * length
    histogram: list[float | None] = [None] * length

    for compact_index, original_index in enumerate(compact_indices):
        signal_value = compact_signal[compact_index]
        signal_line[original_index] = signal_value
        macd_value = macd_line[original_index]
        if signal_value is not None and macd_value is not None:
            histogram[original_index] = macd_value - signal_value

    return macd_line, signal_line, histogram

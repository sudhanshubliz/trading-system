from __future__ import annotations


def calculate_rsi(values: list[float], period: int = 14) -> list[float | None]:
    length = len(values)
    if period <= 0 or length <= period:
        return [None] * length

    result: list[float | None] = [None] * length
    gains: list[float] = []
    losses: list[float] = []

    for index in range(1, length):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    if average_loss == 0:
        result[period] = 100.0
    else:
        rs = average_gain / average_loss
        result[period] = 100 - (100 / (1 + rs))

    for index in range(period + 1, length):
        current_gain = gains[index - 1]
        current_loss = losses[index - 1]
        average_gain = ((average_gain * (period - 1)) + current_gain) / period
        average_loss = ((average_loss * (period - 1)) + current_loss) / period

        if average_loss == 0:
            result[index] = 100.0
            continue

        rs = average_gain / average_loss
        result[index] = 100 - (100 / (1 + rs))

    return result

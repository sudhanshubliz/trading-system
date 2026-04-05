from __future__ import annotations


def calculate_vwap(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> list[float | None]:
    length = min(len(highs), len(lows), len(closes), len(volumes))
    if length == 0:
        return []

    result: list[float | None] = []
    cumulative_price_volume = 0.0
    cumulative_volume = 0.0

    for index in range(length):
        typical_price = (highs[index] + lows[index] + closes[index]) / 3
        volume = volumes[index]
        cumulative_price_volume += typical_price * volume
        cumulative_volume += volume

        if cumulative_volume <= 0:
            result.append(None)
        else:
            result.append(cumulative_price_volume / cumulative_volume)

    return result

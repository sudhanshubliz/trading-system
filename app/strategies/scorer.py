from __future__ import annotations


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_signal(
    *,
    trend_alignment: float,
    momentum: float,
    volume_confirmation: float,
    structure_quality: float,
) -> int:
    weighted_score = (
        (_clamp_unit(trend_alignment) * 0.35)
        + (_clamp_unit(momentum) * 0.25)
        + (_clamp_unit(volume_confirmation) * 0.20)
        + (_clamp_unit(structure_quality) * 0.20)
    ) * 100
    return int(round(max(0.0, min(100.0, weighted_score))))

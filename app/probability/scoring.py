from __future__ import annotations

import math


def compute_brier_score(predictions: list[float], outcomes: list[int | bool]) -> float:
    usable = [(max(0.0, min(1.0, float(p))), 1.0 if bool(o) else 0.0) for p, o in zip(predictions, outcomes, strict=False)]
    if not usable:
        return 0.0
    return round(sum((prediction - outcome) ** 2 for prediction, outcome in usable) / len(usable), 6)


def compute_log_loss(predictions: list[float], outcomes: list[int | bool]) -> float:
    usable = [(min(max(float(p), 1e-6), 1 - 1e-6), 1.0 if bool(o) else 0.0) for p, o in zip(predictions, outcomes, strict=False)]
    if not usable:
        return 0.0
    return round(
        -sum((outcome * math.log(prediction)) + ((1.0 - outcome) * math.log(1.0 - prediction)) for prediction, outcome in usable)
        / len(usable),
        6,
    )

from __future__ import annotations

import math

from app.probability.types import ProbabilityEvidence, ProbabilityUpdate


def clamp_probability(value: float) -> float:
    return max(1e-6, min(1 - 1e-6, value))


def _logit(probability: float) -> float:
    probability = clamp_probability(probability)
    return math.log(probability / (1.0 - probability))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def update_probability(prior: float, evidence: list[ProbabilityEvidence]) -> ProbabilityUpdate:
    prior = clamp_probability(prior)
    running_log_odds = _logit(prior)
    total_weight = 0.0
    contributions: list[dict[str, float | str]] = []
    for item in evidence:
        confidence = max(0.0, min(1.0, item.confidence))
        weight = max(0.0, item.weight)
        decay = max(0.0, min(1.0, item.half_life_decay))
        bias = max(-1.0, min(1.0, item.direction_bias))
        scaled_shift = bias * confidence * weight * decay * 2.2
        total_weight += weight * decay
        running_log_odds += scaled_shift
        contributions.append(
            {
                "source_name": item.source_name,
                "direction_bias": round(bias, 6),
                "confidence": round(confidence, 6),
                "weight": round(weight, 6),
                "decay": round(decay, 6),
                "shift": round(scaled_shift, 6),
            }
        )
    posterior = clamp_probability(_sigmoid(running_log_odds))
    effective_confidence = max(0.0, min(1.0, abs(posterior - 0.5) * 2.0))
    return ProbabilityUpdate(
        prior=round(prior, 6),
        posterior=round(posterior, 6),
        total_weight=round(total_weight, 6),
        effective_confidence=round(effective_confidence, 6),
        contributions=contributions,
        metadata={"evidence_count": len(evidence)},
    )

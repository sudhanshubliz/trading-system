from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProbabilityEvidence:
    source_name: str
    direction_bias: float
    confidence: float
    weight: float = 1.0
    half_life_decay: float = 1.0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ProbabilityUpdate:
    prior: float
    posterior: float
    total_weight: float
    effective_confidence: float
    contributions: list[dict[str, float | str]] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class CalibrationBucket:
    bucket_label: str
    lower_bound: float
    upper_bound: float
    sample_count: int
    mean_prediction: float
    observed_frequency: float

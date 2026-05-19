from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class StrategyDecisionCandidate:
    candidate_id: str
    source_name: str
    strategy_family: str
    symbol_or_market: str
    direction: str
    confidence: float
    expected_value_bps: float
    liquidity_score: float
    freshness_score: float
    execution_quality_score: float
    provider_health_score: float
    regime_score: float
    exposure_score: float
    historical_performance_score: float
    overall_score: float
    timestamp: datetime
    expected_holding_period: str
    tradable: bool
    requires_risk_review: bool
    source_reference_id: str | None = None
    strategy_name: str | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    reward_risk_ratio: float | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyOwnerDecision:
    decision_id: str
    candidate_id: str
    source_name: str
    strategy_family: str
    symbol_or_market: str
    direction: str
    status: str
    overall_score: float
    forwarded_to_risk: bool
    rejection_reason: str | None
    risk_assessment_id: str | None
    metrics_snapshot: dict[str, float | str | bool | None]
    explanation: list[str]
    timestamp: datetime
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyOwnerEvaluationResult:
    candidates: list[StrategyDecisionCandidate] = field(default_factory=list)
    decisions: list[StrategyOwnerDecision] = field(default_factory=list)
    accepted_count: int = 0
    rejected_count: int = 0
    forwarded_to_risk_count: int = 0


@dataclass(slots=True)
class StrategyOwnerSummary:
    candidate_count: int
    decision_count: int
    accepted_count: int
    rejected_count: int
    forwarded_to_risk_count: int
    active_strategy_families: list[str] = field(default_factory=list)
    top_rejection_reasons: list[str] = field(default_factory=list)
    generated_at: datetime | None = None

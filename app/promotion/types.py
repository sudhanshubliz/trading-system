from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class StrategyPromotionStatus:
    strategy_name: str
    current_stage: str
    sample_count: int
    net_expectancy_after_costs: float
    drawdown: float
    execution_quality_avg: float
    provider_health_score: float
    incident_count: int
    last_review_at: datetime | None
    eligible_for_promotion: bool
    promotion_explanation: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PromotionReview:
    review_id: str
    strategy_name: str
    stage_name: str
    decision: str
    reviewed_at: datetime
    explanation: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


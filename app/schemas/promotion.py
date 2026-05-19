from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StrategyPromotionStatusResponse(BaseModel):
    strategy_name: str
    current_stage: str
    sample_count: int
    net_expectancy_after_costs: float
    drawdown: float
    execution_quality_avg: float
    provider_health_score: float
    incident_count: int
    last_review_at: datetime | None = None
    eligible_for_promotion: bool
    promotion_explanation: list[str] = Field(default_factory=list)


class PromotionReviewResponse(BaseModel):
    review_id: str
    strategy_name: str
    stage_name: str
    decision: str
    reviewed_at: datetime
    explanation: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class StrategyPromotionStatusListResponse(BaseModel):
    items: list[StrategyPromotionStatusResponse] = Field(default_factory=list)
    count: int


class PromotionReviewListResponse(BaseModel):
    items: list[PromotionReviewResponse] = Field(default_factory=list)
    count: int


from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StrategyDecisionCandidateResponse(BaseModel):
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
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class StrategyOwnerDecisionResponse(BaseModel):
    decision_id: str
    candidate_id: str
    source_name: str
    strategy_family: str
    symbol_or_market: str
    direction: str
    status: str
    overall_score: float
    forwarded_to_risk: bool
    rejection_reason: str | None = None
    risk_assessment_id: str | None = None
    metrics_snapshot: dict[str, float | str | bool | None] = Field(default_factory=dict)
    explanation: list[str] = Field(default_factory=list)
    timestamp: datetime
    metadata: dict[str, object] = Field(default_factory=dict)


class StrategyOwnerEvaluateRequest(BaseModel):
    symbols: list[str] | None = None
    markets: list[str] | None = None


class StrategyOwnerCandidateListResponse(BaseModel):
    items: list[StrategyDecisionCandidateResponse] = Field(default_factory=list)
    count: int


class StrategyOwnerDecisionListResponse(BaseModel):
    items: list[StrategyOwnerDecisionResponse] = Field(default_factory=list)
    count: int


class StrategyOwnerSummaryResponse(BaseModel):
    candidate_count: int
    decision_count: int
    accepted_count: int
    rejected_count: int
    forwarded_to_risk_count: int
    active_strategy_families: list[str] = Field(default_factory=list)
    top_rejection_reasons: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


class StrategyOwnerEvaluationResponse(BaseModel):
    candidates: list[StrategyDecisionCandidateResponse] = Field(default_factory=list)
    decisions: list[StrategyOwnerDecisionResponse] = Field(default_factory=list)
    accepted_count: int
    rejected_count: int
    forwarded_to_risk_count: int

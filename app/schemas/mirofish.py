from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MiroFishRunRequest(BaseModel):
    symbol_or_market: str
    payload: dict[str, object] = Field(default_factory=dict)


class MiroFishScenarioResponse(BaseModel):
    run_id: str
    scenario_name: str
    symbol_or_market: str
    expected_volatility_shift: float
    expected_crowd_bias: float
    scenario_confidence: float
    timestamp: datetime
    metadata: dict[str, object] = Field(default_factory=dict)

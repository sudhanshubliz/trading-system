from __future__ import annotations

from datetime import datetime

from typing import Literal

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
    direction_bias: str = "neutral"
    explanation: str = ""
    source_name: str = "mirofish_simulation"
    advisory_only: bool = True
    provider_status: str = "unknown"
    metadata: dict[str, object] = Field(default_factory=dict)


class MiroFishExternalScenarioRequest(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=128)
    symbol_or_market: str = Field(min_length=1, max_length=128)
    simulation_timestamp: datetime
    direction_bias: Literal["long", "short", "neutral"]
    expected_crowd_bias: float = Field(ge=-1.0, le=1.0)
    expected_volatility_shift: float = Field(ge=0.0, le=10.0)
    scenario_confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(default="", max_length=4000)
    source_run_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, object] = Field(default_factory=dict)


class MiroFishRemoteSyncRequest(BaseModel):
    simulation_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    scenario_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    symbol_or_market: str = Field(min_length=1, max_length=128)
    simulation_timestamp: datetime
    direction_bias: Literal["long", "short", "neutral"]
    expected_crowd_bias: float = Field(ge=-1.0, le=1.0)
    expected_volatility_shift: float = Field(ge=0.0, le=10.0)
    scenario_confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(default="", max_length=4000)
    metadata: dict[str, object] = Field(default_factory=dict)


class MiroFishHealthResponse(BaseModel):
    status: str
    latency_ms: float | None = None
    success_rate: float = 0.0
    stale_data_flag: bool = True
    error_count: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

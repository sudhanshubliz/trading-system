from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ExperimentArtifactResponse(BaseModel):
    artifact_id: str
    run_id: str
    artifact_type: str
    uri: str
    created_at: datetime
    metadata: dict[str, object] = Field(default_factory=dict)


class ResearchExperimentResponse(BaseModel):
    experiment_id: str
    experiment_name: str
    strategy_family: str
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, object] = Field(default_factory=dict)
    artifacts: list[ExperimentArtifactResponse] = Field(default_factory=list)


class ResearchExperimentListResponse(BaseModel):
    items: list[ResearchExperimentResponse] = Field(default_factory=list)
    count: int


class ExperimentRunResponse(BaseModel):
    run_id: str
    experiment_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    metrics: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    artifacts: list[ExperimentArtifactResponse] = Field(default_factory=list)


class ExperimentRunListResponse(BaseModel):
    items: list[ExperimentRunResponse] = Field(default_factory=list)
    count: int


class BackfillJobRequest(BaseModel):
    dataset_type: str
    provider_name: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    force: bool = False
    notes: list[str] = Field(default_factory=list)


class BackfillJobResponse(BaseModel):
    job_id: str
    dataset_type: str
    provider_name: str
    time_range: dict[str, str | None] = Field(default_factory=dict)
    status: str
    records_requested: int
    records_written: int
    started_at: datetime
    finished_at: datetime | None = None
    error_summary: str | None = None
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class BackfillJobListResponse(BaseModel):
    items: list[BackfillJobResponse] = Field(default_factory=list)
    count: int

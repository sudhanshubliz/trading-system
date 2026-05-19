from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ResearchExperiment:
    experiment_id: str
    experiment_name: str
    strategy_family: str
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ExperimentRun:
    run_id: str
    experiment_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    metrics: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ExperimentArtifact:
    artifact_id: str
    run_id: str
    artifact_type: str
    uri: str
    created_at: datetime
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class BackfillJob:
    job_id: str
    dataset_type: str
    provider_name: str
    time_range: dict[str, str | None]
    status: str
    records_requested: int
    records_written: int
    started_at: datetime
    finished_at: datetime | None = None
    error_summary: str | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

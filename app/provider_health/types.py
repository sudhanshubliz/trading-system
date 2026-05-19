from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ProviderHealthSnapshot:
    snapshot_id: str
    provider_name: str
    status: str
    latency_ms: float | None
    success_rate: float
    stale_data_flag: bool
    error_count: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    observed_at: datetime
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderIngestRun:
    run_id: str
    provider_name: str
    dataset_type: str
    requested_at: datetime
    completed_at: datetime | None
    status: str
    records_requested: int
    records_written: int
    error_summary: str | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.alpha_fusion.types import AlphaFeatureSnapshot


@dataclass(frozen=True, slots=True)
class FeatureCatalogEntry:
    name: str
    family: str
    description: str
    output_type: str
    timeframes_supported: bool = True


@dataclass(slots=True)
class FeatureRun:
    run_id: str
    symbol: str
    source_name: str
    status: str
    generated_at: datetime
    timeframes: list[str] = field(default_factory=list)
    catalog_version: str = "0.1.0"
    feature_snapshot: AlphaFeatureSnapshot | None = None
    metadata: dict[str, object] = field(default_factory=dict)

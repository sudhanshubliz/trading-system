from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class AllocationRecommendation:
    allocation_id: str
    strategy_name: str
    scope_key: str
    capital_pct: float
    status: str
    explanation: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class PortfolioBrainSnapshot:
    snapshot_id: str
    execution_mode: str
    generated_at: datetime
    capital_by_strategy_family: dict[str, float]
    capital_by_symbol_or_market: dict[str, float]
    gross_exposure_cap: float
    net_exposure_guidance: float
    strategy_throttles: dict[str, float]
    strategy_disables: list[str]
    watchlist: list[str]
    explanation: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


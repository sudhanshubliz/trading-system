from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class MiroFishScenarioSummary:
    run_id: str
    scenario_name: str
    symbol_or_market: str
    expected_volatility_shift: float
    expected_crowd_bias: float
    scenario_confidence: float
    timestamp: datetime
    metadata: dict[str, object] = field(default_factory=dict)

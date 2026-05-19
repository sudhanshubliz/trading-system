from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class BasisFundingOpportunity:
    opportunity_id: str
    symbol: str
    timestamp: datetime
    signal_family: str
    basis_value: float | None
    funding_value: float | None
    basis_zscore: float | None
    funding_zscore: float | None
    gross_edge_estimate: float
    fee_estimate: float
    slippage_estimate: float
    net_edge_estimate: float
    confidence: float
    recommended_direction: str
    expected_holding_period: str
    explanation: list[str] = field(default_factory=list)
    opportunity_type: str = "none"
    tradable: bool = False
    metadata: dict[str, object] = field(default_factory=dict)

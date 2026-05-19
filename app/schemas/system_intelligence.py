from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.arbitrage import BasisFundingOpportunityResponse
from app.schemas.alpha import FusedAlphaSignalResponse
from app.schemas.event_signals import EventSignalResponse
from app.schemas.microstructure import MicrostructureSnapshotResponse
from app.schemas.mirofish import MiroFishScenarioResponse
from app.schemas.polymarket import PolymarketOpportunityResponse
from app.schemas.provider_health import ProviderHealthSummaryResponse
from app.schemas.regime import RegimeSnapshotResponse
from app.schemas.risk_locks import RiskLockEventResponse
from app.schemas.wallets import WalletProfileResponse


class SafeModeResponse(BaseModel):
    enable_live_trading: bool
    live_trading_armed: bool
    execution_mode: str


class SystemIntelligenceSummaryResponse(BaseModel):
    supported_symbols: list[str] = Field(default_factory=list)
    latest_fused_opportunities: list[FusedAlphaSignalResponse] = Field(default_factory=list)
    current_regimes: list[RegimeSnapshotResponse] = Field(default_factory=list)
    feature_catalog_size: int
    active_risk_locks: list[RiskLockEventResponse] = Field(default_factory=list)
    basis_funding_highlights: list[BasisFundingOpportunityResponse] = Field(default_factory=list)
    microstructure_status: list[MicrostructureSnapshotResponse] = Field(default_factory=list)
    polymarket_highlights: list[PolymarketOpportunityResponse] = Field(default_factory=list)
    wallet_highlights: list[WalletProfileResponse] = Field(default_factory=list)
    event_highlights: list[EventSignalResponse] = Field(default_factory=list)
    provider_health: ProviderHealthSummaryResponse | dict[str, object] = Field(default_factory=dict)
    mirofish_latest: MiroFishScenarioResponse | None = None
    tradability_state: dict[str, object] = Field(default_factory=dict)
    safe_mode: SafeModeResponse
    promotion_blockers: list[dict[str, object]] = Field(default_factory=list)
    allocation_snapshot: dict[str, object] | None = None
    incident_summary: dict[str, object] = Field(default_factory=dict)
    backfill_status: dict[str, object] = Field(default_factory=dict)

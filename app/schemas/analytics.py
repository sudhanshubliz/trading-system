from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StrategyAttributionItemResponse(BaseModel):
    strategy_name: str
    total_pnl: float
    win_rate: float
    expectancy: float
    drawdown_pct: float
    capital_efficiency: float
    average_holding_minutes: float
    trade_count: int
    contribution_pct: float
    regime_breakdown: dict[str, float] = Field(default_factory=dict)


class SymbolAttributionItemResponse(BaseModel):
    symbol: str
    total_pnl: float
    win_rate: float
    trade_count: int
    contribution_pct: float
    average_holding_minutes: float
    execution_mode_split: dict[str, int] = Field(default_factory=dict)


class PortfolioAnalyticsResponse(BaseModel):
    total_pnl: float
    total_trades: int
    win_rate: float
    expectancy: float
    drawdown_pct: float
    execution_mode_split: dict[str, int] = Field(default_factory=dict)
    top_strategies: list[StrategyAttributionItemResponse] = Field(default_factory=list)
    top_symbols: list[SymbolAttributionItemResponse] = Field(default_factory=list)
    current_regime: str
    lookback_days: int
    timestamp: datetime | None = None


class StrategyAttributionResponse(BaseModel):
    items: list[StrategyAttributionItemResponse] = Field(default_factory=list)
    count: int
    timestamp: datetime


class SymbolAttributionResponse(BaseModel):
    items: list[SymbolAttributionItemResponse] = Field(default_factory=list)
    count: int
    timestamp: datetime


class RegimeAnalyticsResponse(BaseModel):
    current_regime: str
    supported_regimes: list[str] = Field(default_factory=list)
    strategy_regime_leaders: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime | None = None


class AttributionSummaryResponse(BaseModel):
    portfolio: PortfolioAnalyticsResponse
    strategies: StrategyAttributionResponse
    symbols: SymbolAttributionResponse
    regime: RegimeAnalyticsResponse
    timestamp: datetime

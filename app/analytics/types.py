from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class StrategyAttribution:
    strategy_name: str
    total_pnl: float
    win_rate: float
    expectancy: float
    drawdown_pct: float
    capital_efficiency: float
    average_holding_minutes: float
    trade_count: int
    contribution_pct: float
    regime_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class SymbolAttribution:
    symbol: str
    total_pnl: float
    win_rate: float
    trade_count: int
    contribution_pct: float
    average_holding_minutes: float
    execution_mode_split: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class PortfolioMetrics:
    total_pnl: float
    total_trades: int
    win_rate: float
    expectancy: float
    drawdown_pct: float
    execution_mode_split: dict[str, int] = field(default_factory=dict)
    top_strategies: list[StrategyAttribution] = field(default_factory=list)
    top_symbols: list[SymbolAttribution] = field(default_factory=list)
    current_regime: str = "ranging"
    lookback_days: int = 30
    timestamp: datetime | None = None


@dataclass(slots=True)
class RegimeSummary:
    current_regime: str
    supported_regimes: list[str] = field(default_factory=list)
    strategy_regime_leaders: dict[str, str] = field(default_factory=dict)
    timestamp: datetime | None = None

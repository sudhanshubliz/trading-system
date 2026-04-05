from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReportPointResponse(BaseModel):
    timestamp: datetime
    equity: float


class DrawdownPointResponse(BaseModel):
    timestamp: datetime
    equity: float
    drawdown_pct: float


class ReportItemResponse(BaseModel):
    group: str
    total_trades: int
    win_rate: float
    net_pnl: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    average_hold_minutes: float
    risk_per_trade: float
    equity_curve: list[ReportPointResponse]
    drawdown_timeline: list[DrawdownPointResponse]


class ReportResponse(BaseModel):
    scope: str
    execution_mode: str
    generated_at: datetime
    count: int
    items: list[ReportItemResponse]

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.config.settings import Settings
from app.risk.types import AccountState, ExposureState, RiskAssessment, RiskSummary


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExposureManager:
    def __init__(self, settings: Settings, *, time_provider: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self.time_provider = time_provider or utc_now

    def get_reserved_risk_amount(self, assessments: list[RiskAssessment]) -> float:
        return sum(
            assessment.risk_amount
            for assessment in assessments
            if assessment.final_decision == "approved_for_review"
        )

    def get_account_state(self, assessments: list[RiskAssessment]) -> AccountState:
        balance = self.settings.paper_account_start_balance
        reserved_risk_amount = self.get_reserved_risk_amount(assessments)
        available_balance = max(balance - reserved_risk_amount, 0.0)
        return AccountState(
            balance=balance,
            equity=balance,
            available_balance=available_balance,
            realized_pnl_daily=0.0,
            realized_pnl_weekly=0.0,
        )

    def get_exposure_state(self, assessments: list[RiskAssessment]) -> ExposureState:
        reserved_risk_amount = self.get_reserved_risk_amount(assessments)
        balance = self.settings.paper_account_start_balance
        open_positions = sum(
            1 for assessment in assessments if assessment.final_decision == "approved_for_review"
        )
        open_risk_pct = (reserved_risk_amount / balance) * 100 if balance > 0 else 0.0
        return ExposureState(
            open_positions=open_positions,
            open_risk_pct=open_risk_pct,
            reserved_risk_amount=reserved_risk_amount,
        )

    def get_risk_summary(self, assessments: list[RiskAssessment]) -> RiskSummary:
        account_state = self.get_account_state(assessments)
        exposure_state = self.get_exposure_state(assessments)
        daily_drawdown_pct = 0.0
        weekly_drawdown_pct = 0.0
        global_risk_lock = (
            daily_drawdown_pct >= self.settings.max_daily_drawdown_pct
            or weekly_drawdown_pct >= self.settings.max_weekly_drawdown_pct
        )
        return RiskSummary(
            account_balance=account_state.balance,
            equity=account_state.equity,
            available_balance=account_state.available_balance,
            open_risk_pct=exposure_state.open_risk_pct,
            daily_drawdown_pct=daily_drawdown_pct,
            weekly_drawdown_pct=weekly_drawdown_pct,
            max_risk_per_trade_pct=self.settings.max_risk_per_trade_pct,
            max_concurrent_positions=self.settings.max_concurrent_positions,
            open_positions=exposure_state.open_positions,
            global_risk_lock=global_risk_lock,
            timestamp=self.time_provider(),
        )

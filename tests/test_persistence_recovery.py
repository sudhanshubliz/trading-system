from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import get_settings
from app.execution.service import ExecutionService
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.risk.types import RiskAssessment, RiskCheckResult


class FakeMarketDataService:
    async def get_snapshot(self, symbol: str) -> dict[str, float | None]:
        return {"last_price": 101.0}

    async def get_health(self) -> dict[str, str]:
        return {"status": "ok"}


class FakeRiskService:
    def __init__(self, assessment: RiskAssessment) -> None:
        self.assessment = assessment

    def get_assessment(self, assessment_id: str) -> RiskAssessment | None:
        if self.assessment.assessment_id == assessment_id:
            return self.assessment
        return None


def _build_settings(tmp_path: Path):
    return get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'persistence_recovery.db'}",
            "stale_market_data_blocks_trading": True,
        }
    )


def _build_assessment() -> RiskAssessment:
    return RiskAssessment(
        assessment_id="ras_recovery_001",
        signal_id="sig_recovery_001",
        symbol="BTCUSDT",
        side="long",
        strategy_name="trend_follow_continuation",
        final_decision="approved_for_review",
        account_balance=10000.0,
        max_risk_pct=2.0,
        risk_amount=50.0,
        stop_distance_abs=5.0,
        stop_distance_pct=5.0,
        position_size=10.0,
        notional_value=1000.0,
        estimated_fee=1.0,
        estimated_slippage_pct=0.0,
        open_risk_pct_before=0.0,
        open_risk_pct_after=0.5,
        daily_drawdown_pct=0.0,
        weekly_drawdown_pct=0.0,
        min_reward_risk_ratio=1.5,
        actual_reward_risk_ratio=2.0,
        confidence_threshold=65,
        risk_score=85,
        trade_classification="A+",
        passed_checks_count=10,
        failed_checks_count=0,
        checks=[RiskCheckResult(name="dummy", passed=True)],
        rejection_reasons=[],
        generated_trade_plan={
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target_1": 110.0,
            "target_2": 120.0,
            "position_size": 10.0,
            "notional_value": 1000.0,
            "mode": "paper",
            "approved_for_review": True,
        },
        assessed_at=datetime(2026, 4, 3, 10, 0, tzinfo=timezone.utc),
    )


def test_persistence_recovery(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    approvals_repo = ApprovalsRepository(session_factory)
    trades_repo = TradesRepository(session_factory)
    positions_repo = PositionsRepository(session_factory)
    events_repo = EventsRepository(session_factory)
    assessment = _build_assessment()

    service = ExecutionService(
        settings=settings,
        risk_service=FakeRiskService(assessment),
        market_data_service=FakeMarketDataService(),
        approvals_repo=approvals_repo,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        events_repo=events_repo,
        persistence_session_factory=session_factory,
    )

    import asyncio

    approval = asyncio.run(service.create_approval_from_assessment(assessment.assessment_id))
    asyncio.run(service.approve_and_execute(approval.approval_id))

    recovered = ExecutionService(
        settings=settings,
        risk_service=FakeRiskService(assessment),
        market_data_service=FakeMarketDataService(),
        approvals_repo=approvals_repo,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        events_repo=events_repo,
        persistence_session_factory=session_factory,
    )
    recovered.recover_state()

    approvals = asyncio.run(recovered.list_approvals())
    positions = asyncio.run(recovered.get_positions())
    trades = asyncio.run(recovered.get_trades())

    assert len(approvals) == 1
    assert approvals[0].status == "executed"
    assert len(positions) == 1
    assert positions[0].status == "open"
    assert len(trades) == 1
    assert trades[0].execution_mode == "paper"

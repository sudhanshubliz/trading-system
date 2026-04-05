from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.execution.service import ExecutionService
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.risk.types import RiskAssessment, RiskCheckResult
from app.shadow.runner import ShadowRunner
from app.shadow.service import ShadowService
from app.signals.types import CandidateSignal


class FakeMarketDataService:
    async def get_health(self) -> dict[str, str]:
        return {"status": "ok"}

    async def get_snapshot(self, symbol: str) -> dict[str, float | None]:
        return {"last_price": 101.0}


class FakeSignalService:
    async def evaluate_symbols(self, symbols=None):
        return [
            CandidateSignal(
                signal_id="sig_shadow_001",
                symbol="BTCUSDT",
                side="long",
                strategy_name="trend_follow_continuation",
                confidence_score=80,
                entry_price=100.0,
                stop_loss=95.0,
                target_1=110.0,
                target_2=120.0,
                reward_risk_ratio=2.0,
                rationale=["shadow"],
                indicators_snapshot={},
                generated_at=datetime(2026, 4, 3, 10, 0, tzinfo=timezone.utc),
            )
        ]


class FakeRiskService:
    def __init__(self) -> None:
        self.assessment = RiskAssessment(
            assessment_id="ras_shadow_001",
            signal_id="sig_shadow_001",
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
                "mode": "shadow",
                "approved_for_review": True,
            },
            assessed_at=datetime(2026, 4, 3, 10, 0, tzinfo=timezone.utc),
        )

    async def validate_signal_payload(self, payload):
        return self.assessment

    def get_assessment(self, assessment_id: str) -> RiskAssessment | None:
        if assessment_id == self.assessment.assessment_id:
            return self.assessment
        return None


def test_shadow_mode_flow(tmp_path: Path) -> None:
    settings = get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'shadow_mode.db'}",
            "execution_mode": "shadow",
            "shadow_mode_enabled": True,
            "shadow_auto_approve": True,
            "global_pause": False,
        }
    )
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    approvals_repo = ApprovalsRepository(session_factory)
    trades_repo = TradesRepository(session_factory)
    positions_repo = PositionsRepository(session_factory)
    events_repo = EventsRepository(session_factory)
    execution_service = ExecutionService(
        settings=settings,
        risk_service=FakeRiskService(),
        market_data_service=FakeMarketDataService(),
        execution_mode="shadow",
        approvals_repo=approvals_repo,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        events_repo=events_repo,
        persistence_session_factory=session_factory,
    )
    runner = ShadowRunner(
        signal_service=FakeSignalService(),
        risk_service=FakeRiskService(),
        execution_service=execution_service,
        market_data_service=FakeMarketDataService(),
        auto_approve=True,
        events_repo=events_repo,
    )
    service = ShadowService(runner, settings=settings)

    from app.main import app

    with TestClient(app) as client:
        app.state.shadow_service = service
        start_response = client.post("/api/v1/shadow/start")
        import asyncio

        asyncio.run(service.run_cycle(["BTCUSDT"]))
        status_response = client.get("/api/v1/shadow/status")
        stop_response = client.post("/api/v1/shadow/stop")

    assert start_response.status_code == 200
    assert status_response.status_code == 200
    assert stop_response.status_code == 200
    persisted_trades = trades_repo.list_trades("shadow")
    assert len(persisted_trades) == 1
    assert persisted_trades[0].execution_mode == "shadow"

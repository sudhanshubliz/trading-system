from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.execution.service import ExecutionService
from app.execution.types import Trade
from app.market_data.types import OrderBookLevel, OrderBookSnapshot, TickerSnapshot
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

    async def get_snapshot(self, symbol: str) -> TickerSnapshot:
        now = datetime.now(timezone.utc)
        return TickerSnapshot(
            symbol=symbol,
            last_price=101.0,
            bid_price=100.8,
            ask_price=101.2,
            best_bid_qty=25.0,
            best_ask_qty=25.0,
            snapshot_time=now,
            ticker_updated_at=now,
            orderbook_updated_at=now,
        )

    async def get_order_book(self, symbol: str) -> OrderBookSnapshot:
        now = datetime.now(timezone.utc)
        return OrderBookSnapshot(
            symbol=symbol,
            bids=[OrderBookLevel(price=100.8, quantity=25.0)],
            asks=[OrderBookLevel(price=101.2, quantity=25.0)],
            updated_at=now,
        )


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
    import time

    settings = get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'shadow_mode.db'}",
            "execution_mode": "shadow",
            "shadow_mode_enabled": True,
            "shadow_auto_approve": True,
            "shadow_cycle_interval_sec": 1,
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
        for _ in range(10):
            if runner.last_cycle_at is not None:
                break
            time.sleep(0.1)
        status_response = client.get("/api/v1/shadow/status")
        stop_response = client.post("/api/v1/shadow/stop")

    assert start_response.status_code == 200
    assert status_response.status_code == 200
    assert stop_response.status_code == 200
    evidence = status_response.json()["evidence"]
    assert evidence["stable"] is False
    assert "shadow_duration_below_minimum" in evidence["blockers"]
    assert "shadow_closed_trades_below_minimum" in evidence["blockers"]
    persisted_trades = trades_repo.list_trades("shadow")
    assert len(persisted_trades) == 1
    assert persisted_trades[0].execution_mode == "shadow"


def test_shadow_start_launches_background_cycle(tmp_path: Path) -> None:
    import asyncio

    settings = get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'shadow_loop.db'}",
            "execution_mode": "shadow",
            "shadow_mode_enabled": True,
            "shadow_auto_approve": True,
            "shadow_cycle_interval_sec": 1,
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

    async def scenario() -> None:
        await service.start_shadow()
        for _ in range(10):
            if runner.last_cycle_at is not None:
                break
            await asyncio.sleep(0.1)
        await service.stop_shadow()

    asyncio.run(scenario())

    persisted_trades = trades_repo.list_trades("shadow")
    assert runner.last_cycle_at is not None
    assert len(persisted_trades) >= 1


def test_shadow_evidence_excludes_trades_before_current_window() -> None:
    now = datetime.now(timezone.utc)

    def trade(trade_id: str, opened_at: datetime, pnl: float) -> Trade:
        return Trade(
            trade_id=trade_id,
            approval_id=f"approval_{trade_id}",
            assessment_id=f"assessment_{trade_id}",
            signal_id=f"signal_{trade_id}",
            position_id=f"position_{trade_id}",
            symbol="BTCUSDT",
            side="long",
            strategy_name="trend_follow_continuation",
            quantity=1.0,
            execution_price=100.0,
            requested_entry_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=120.0,
            status="closed",
            execution_mode="shadow",
            opened_at=opened_at,
            updated_at=opened_at,
            closed_at=opened_at + timedelta(minutes=5),
            realized_pnl=pnl,
            gross_realized_pnl=pnl + 1.0,
            fees_paid=1.0,
        )

    old_trade = trade("old", now - timedelta(days=2), 100.0)
    current_trade = trade("current", now - timedelta(minutes=30), 10.0)
    runner = SimpleNamespace(
        started_at=now - timedelta(hours=1),
        stopped_at=None,
        running=True,
        cycle_count=3,
        last_error=None,
        execution_service=SimpleNamespace(snapshot_recorded_trades=lambda: [old_trade, current_trade]),
    )
    settings = get_settings().model_copy(
        update={
            "shadow_min_evidence_days": 0,
            "shadow_min_closed_trades": 1,
            "shadow_min_profit_factor": 1.0,
            "shadow_min_expectancy": 0.0,
        }
    )

    evidence = ShadowService(runner, settings=settings)._build_evidence()

    assert evidence["stable"] is True
    assert evidence["total_trades"] == 1
    assert evidence["net_realized_pnl"] == 10.0

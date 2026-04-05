from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.live import router as live_router
from app.config.settings import get_settings
from app.db.base import Base
from app.db.models import SystemState
from app.execution.live_adapter import LiveAdapterError
from app.execution.service import ExecutionService
from app.live.controller import LiveController
from app.live.locks import LiveLockManager
from app.live.types import LiveExecutionResult, LiveLockType, LiveOrderResult
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.locks_repo import LocksRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.risk_repo import RiskRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.risk.types import RiskAssessment, RiskCheckResult


class FakeExecutionState:
    def __init__(self, *, paused: bool = False) -> None:
        self.paused = paused

    def is_paused(self) -> bool:
        return self.paused


class FakeMarketDataService:
    def __init__(self, *, last_price: float = 100.0, age_seconds: int = 0) -> None:
        self.last_price = last_price
        self.age_seconds = age_seconds

    async def get_snapshot(self, symbol: str) -> dict[str, object]:
        return {
            "symbol": symbol,
            "last_price": self.last_price,
            "snapshot_time": datetime.now(timezone.utc) - timedelta(seconds=self.age_seconds),
        }


class FakeLiveAdapter:
    def __init__(self) -> None:
        self.place_order_calls: list[dict[str, object]] = []

    def place_order(self, payload, *, snapshot=None):
        self.place_order_calls.append({"payload": payload, "snapshot": snapshot})
        return LiveOrderResult(
            client_order_id=payload.client_order_id,
            exchange_order_id="123456",
            status="NEW",
            symbol=payload.symbol,
            side=payload.side,
            order_type=payload.order_type,
            quantity=payload.quantity,
            limit_price=payload.limit_price,
            executed_price=payload.limit_price,
        )

    def cancel_order(self, payload):
        return LiveOrderResult(
            client_order_id=str(payload.get("client_order_id") or ""),
            exchange_order_id=str(payload.get("exchange_order_id") or ""),
            status="CANCELED",
            symbol=str(payload.get("symbol") or ""),
            side=str(payload.get("side") or "BUY"),
            order_type=str(payload.get("order_type") or "LIMIT"),
            quantity=float(payload.get("quantity") or 0.0),
            limit_price=float(payload.get("limit_price") or 0.0),
            executed_price=float(payload.get("limit_price") or 0.0),
        )

    def get_order(self, **kwargs):
        return LiveOrderResult(
            client_order_id=str(kwargs.get("client_order_id") or ""),
            exchange_order_id=str(kwargs.get("exchange_order_id") or ""),
            status="NEW",
            symbol=str(kwargs.get("symbol") or ""),
            side="BUY",
            order_type="LIMIT",
            quantity=0.0,
            limit_price=None,
            executed_price=None,
        )

    def get_open_orders(self):
        return []

    def get_positions(self):
        return []

    def ping(self):
        return {"status": "ok"}


class RecordingLiveController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute_live_trade(self, assessment_id: str) -> LiveExecutionResult:
        self.calls.append(assessment_id)
        return LiveExecutionResult(
            allowed=False,
            reasons=["blocked"],
            trade_id=None,
            position_id=None,
            client_order_id=None,
            exchange_order_id=None,
            status="blocked",
            active_locks=[],
        )


def _build_assessment(*, assessment_id: str = "ras_live_001", notional_value: float = 100.0) -> RiskAssessment:
    entry_price = 100.0
    position_size = notional_value / entry_price
    return RiskAssessment(
        assessment_id=assessment_id,
        signal_id=f"sig_{assessment_id}",
        symbol="BTCUSDT",
        side="long",
        strategy_name="trend_follow_continuation",
        final_decision="approved_for_review",
        account_balance=10000.0,
        max_risk_pct=2.0,
        risk_amount=50.0,
        stop_distance_abs=5.0,
        stop_distance_pct=5.0,
        position_size=position_size,
        notional_value=notional_value,
        estimated_fee=1.0,
        estimated_slippage_pct=0.0,
        open_risk_pct_before=0.0,
        open_risk_pct_after=0.5,
        daily_drawdown_pct=0.0,
        weekly_drawdown_pct=0.0,
        min_reward_risk_ratio=1.5,
        actual_reward_risk_ratio=2.0,
        confidence_threshold=65,
        risk_score=90,
        trade_classification="A+",
        passed_checks_count=10,
        failed_checks_count=0,
        checks=[RiskCheckResult(name="ok", passed=True)],
        rejection_reasons=[],
        generated_trade_plan={
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": entry_price,
            "stop_loss": 95.0,
            "target_1": 110.0,
            "target_2": 120.0,
            "position_size": position_size,
            "notional_value": notional_value,
            "mode": "live",
            "approved_for_review": True,
        },
        assessed_at=datetime.now(timezone.utc),
    )


def _build_controller(tmp_path, monkeypatch, *, paused: bool = False, live_max_order_notional: float = 500.0):
    settings = get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'live_control.db'}",
            "enable_live_trading": True,
            "live_require_explicit_approval": False,
            "live_max_order_notional": live_max_order_notional,
            "live_allow_limit_orders": True,
            "live_allow_market_orders": False,
        }
    )
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)

    system_engine = create_engine(
        f"sqlite:///{tmp_path / 'system_state.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(system_engine)
    state_session_factory = sessionmaker(
        bind=system_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr("app.live.controller.SessionLocal", state_session_factory)

    with state_session_factory.begin() as session:
        session.merge(
            SystemState(
                key="global_pause",
                value_json='{"paused": false}',
                updated_at=datetime.now(timezone.utc),
            )
        )

    risk_repo = RiskRepository(session_factory)
    approvals_repo = ApprovalsRepository(session_factory)
    trades_repo = TradesRepository(session_factory)
    positions_repo = PositionsRepository(session_factory)
    events_repo = EventsRepository(session_factory)
    locks_repo = LocksRepository(session_factory)
    adapter = FakeLiveAdapter()
    controller = LiveController(
        settings=settings,
        adapter=adapter,
        lock_manager=LiveLockManager(locks_repo=locks_repo, events_repo=events_repo),
        risk_repo=risk_repo,
        approvals_repo=approvals_repo,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        events_repo=events_repo,
        market_data_service=FakeMarketDataService(),
        execution_service=FakeExecutionState(paused=paused),
    )
    return {
        "settings": settings,
        "controller": controller,
        "risk_repo": risk_repo,
        "locks_repo": locks_repo,
        "adapter": adapter,
    }


def test_live_execute_blocked_when_not_armed(tmp_path, monkeypatch) -> None:
    env = _build_controller(tmp_path, monkeypatch)
    env["risk_repo"].upsert_assessment(_build_assessment())

    result = asyncio.run(env["controller"].execute_live_trade("ras_live_001"))

    assert result.allowed is False
    assert "live_trading_not_armed" in result.reasons
    assert env["adapter"].place_order_calls == []


def test_live_execute_blocked_by_global_pause(tmp_path, monkeypatch) -> None:
    env = _build_controller(tmp_path, monkeypatch, paused=True)
    env["risk_repo"].upsert_assessment(_build_assessment())
    asyncio.run(env["controller"].arm_live_trading())

    result = asyncio.run(env["controller"].execute_live_trade("ras_live_001"))

    assert result.allowed is False
    assert "global_pause_active" in result.reasons
    assert env["adapter"].place_order_calls == []


def test_live_execute_rejects_invalid_order_notional(tmp_path, monkeypatch) -> None:
    env = _build_controller(tmp_path, monkeypatch, live_max_order_notional=50.0)
    env["risk_repo"].upsert_assessment(_build_assessment(notional_value=200.0))
    asyncio.run(env["controller"].arm_live_trading())

    result = asyncio.run(env["controller"].execute_live_trade("ras_live_001"))

    assert result.allowed is False
    assert "order_notional_exceeds_limit" in result.reasons
    assert env["adapter"].place_order_calls == []


def test_live_execute_uses_controller_not_direct_adapter() -> None:
    controller = RecordingLiveController()
    service = ExecutionService(settings=get_settings(), live_controller=controller)

    result = asyncio.run(service.execute_live_assessment("ras_delegate_001"))

    assert controller.calls == ["ras_delegate_001"]
    assert result.status == "blocked"


def test_live_status_endpoint_returns_expected_shape(tmp_path, monkeypatch) -> None:
    env = _build_controller(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(live_router, prefix="/api/v1")
    app.state.live_controller = env["controller"]

    with TestClient(app) as client:
        response = client.get("/api/v1/live/status")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "enabled",
        "armed",
        "execution_mode",
        "can_execute",
        "global_pause",
        "active_locks",
        "stale_market_data",
        "open_live_positions",
        "daily_live_pnl",
        "weekly_live_pnl",
        "timestamp",
    }

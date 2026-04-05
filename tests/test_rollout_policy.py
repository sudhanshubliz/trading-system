from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
from app.db.base import Base
from app.db.models import SystemState
from app.execution.types import Position
from app.live.controller import LiveController
from app.live.locks import LiveLockManager
from app.live.rollout import LiveRolloutPolicy
from app.live.types import LiveOrderRequest, LiveOrderResult, LiveRolloutState
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.locks_repo import LocksRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.risk_repo import RiskRepository
from app.persistence.repositories.rollout_repo import RolloutRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.risk.types import RiskAssessment, RiskCheckResult


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


class FakeExecutionState:
    def __init__(self, *, paused: bool = False) -> None:
        self.paused = paused

    def is_paused(self) -> bool:
        return self.paused


class FakeLiveAdapter:
    def __init__(self) -> None:
        self.place_order_calls: list[dict[str, object]] = []

    def place_order(self, payload, *, snapshot=None):
        self.place_order_calls.append({"payload": payload, "snapshot": snapshot})
        return LiveOrderResult(
            client_order_id=payload.client_order_id,
            exchange_order_id="ord_001",
            status="NEW",
            symbol=payload.symbol,
            side=payload.side,
            order_type=payload.order_type,
            quantity=payload.quantity,
            limit_price=payload.limit_price,
            executed_price=payload.limit_price,
        )

    def get_open_orders(self):
        return []

    def get_positions(self):
        return []


def build_assessment(
    *,
    assessment_id: str = "ras_rollout_001",
    symbol: str = "BTCUSDT",
    strategy_name: str = "trend_follow_continuation",
    notional_value: float = 100.0,
) -> RiskAssessment:
    entry_price = 100.0
    position_size = notional_value / entry_price
    return RiskAssessment(
        assessment_id=assessment_id,
        signal_id=f"sig_{assessment_id}",
        symbol=symbol,
        side="long",
        strategy_name=strategy_name,
        final_decision="approved_for_review",
        account_balance=10000.0,
        max_risk_pct=2.0,
        risk_amount=25.0,
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
            "symbol": symbol,
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


def build_order_request(assessment: RiskAssessment) -> LiveOrderRequest:
    plan = assessment.generated_trade_plan
    return LiveOrderRequest(
        assessment_id=assessment.assessment_id,
        symbol=assessment.symbol,
        side="BUY",
        quantity=float(plan["position_size"]),
        order_type="LIMIT",
        limit_price=float(plan["entry_price"]),
        stop_loss=float(plan["stop_loss"]),
        notional=float(plan["notional_value"]),
        client_order_id=f"client_{assessment.assessment_id}",
    )


def upsert_rollout_state(env: dict[str, object], *, phase: str, capital_limit: float, rollback_active: bool = False) -> None:
    env["rollout_repo"].upsert_rollout_state(  # type: ignore[index]
        LiveRolloutState(
            current_phase=phase,
            current_capital_limit=capital_limit,
            allowed_capital_limit=capital_limit,
            strategy_allocations={},
            symbol_allocations={},
            last_phase_change_at=datetime.now(timezone.utc),
            changed_by="test",
            reason="test_setup",
            rollback_active=rollback_active,
            notes=[],
            updated_at=datetime.now(timezone.utc),
        )
    )


def seed_open_position(
    env: dict[str, object],
    *,
    position_id: str,
    symbol: str,
    strategy_name: str,
    notional_value: float,
) -> None:
    now = datetime.now(timezone.utc)
    quantity = notional_value / 100.0
    env["positions_repo"].upsert_position(  # type: ignore[index]
        Position(
            position_id=position_id,
            trade_id=f"trd_{position_id}",
            approval_id=f"apr_{position_id}",
            assessment_id=f"ras_{position_id}",
            signal_id=f"sig_{position_id}",
            symbol=symbol,
            side="long",
            strategy_name=strategy_name,
            initial_quantity=quantity,
            quantity_open=quantity,
            entry_price=100.0,
            current_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=120.0,
            status="open",
            opened_at=now,
            updated_at=now,
            execution_mode="live",
        )
    )


def build_rollout_env(tmp_path: Path, monkeypatch, *, settings_update: dict[str, object] | None = None) -> dict[str, object]:
    updates = {
        "persistence_enabled": True,
        "persistence_db_url": f"sqlite:///{tmp_path / 'rollout_policy.db'}",
        "enable_live_trading": True,
        "live_require_explicit_approval": False,
        "live_allow_limit_orders": True,
        "live_allow_market_orders": False,
        "rollout_policy_enabled": True,
        "live_phase_default": "disabled",
        "live_allowed_phases": ["disabled", "micro", "limited", "scaled"],
        "live_initial_capital_limit": 100.0,
        "live_max_capital_total": 1000.0,
        "live_scaling_step_capital": 100.0,
        "live_strategy_max_capital_pct": 50.0,
        "live_symbol_max_capital_pct": 40.0,
        "live_portfolio_max_correlated_positions": 2,
    }
    updates.update(settings_update or {})
    settings = get_settings().model_copy(update=updates)
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)

    system_engine = create_engine(
        f"sqlite:///{tmp_path / 'rollout_system_state.db'}",
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
    rollout_repo = RolloutRepository(session_factory)
    rollout_service = LiveRolloutPolicy(
        settings=settings,
        rollout_repo=rollout_repo,
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        events_repo=events_repo,
    )
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
        execution_service=FakeExecutionState(paused=False),
        rollout_service=rollout_service,
    )
    return {
        "settings": settings,
        "controller": controller,
        "adapter": adapter,
        "risk_repo": risk_repo,
        "positions_repo": positions_repo,
        "events_repo": events_repo,
        "rollout_repo": rollout_repo,
        "rollout_service": rollout_service,
        "trades_repo": trades_repo,
    }


def test_rollout_disabled_blocks_live_execution(tmp_path: Path, monkeypatch) -> None:
    env = build_rollout_env(tmp_path, monkeypatch)
    assessment = build_assessment(notional_value=25.0)
    env["risk_repo"].upsert_assessment(assessment)  # type: ignore[index]
    asyncio.run(env["controller"].arm_live_trading())  # type: ignore[index]

    result = asyncio.run(env["controller"].execute_live_trade(assessment.assessment_id))  # type: ignore[index]

    assert result.allowed is False
    assert "rollout_phase_disabled" in result.reasons
    assert env["adapter"].place_order_calls == []  # type: ignore[index]


def test_micro_phase_allows_only_small_capital(tmp_path: Path, monkeypatch) -> None:
    env = build_rollout_env(
        tmp_path,
        monkeypatch,
        settings_update={
            "live_strategy_max_capital_pct": 100.0,
            "live_symbol_max_capital_pct": 100.0,
        },
    )
    env["rollout_service"].set_rollout_phase("micro", changed_by="test", reason="enable_micro")  # type: ignore[index]

    small_assessment = build_assessment(assessment_id="ras_micro_ok", notional_value=80.0)
    small = env["rollout_service"].evaluate_trade_under_rollout(  # type: ignore[index]
        order_request=build_order_request(small_assessment),
        assessment=small_assessment,
    )
    large_assessment = build_assessment(assessment_id="ras_micro_block", notional_value=150.0)
    large = env["rollout_service"].evaluate_trade_under_rollout(  # type: ignore[index]
        order_request=build_order_request(large_assessment),
        assessment=large_assessment,
    )

    assert small.allowed is True
    assert large.allowed is False
    assert "rollout_capital_limit_exceeded" in large.reasons


def test_strategy_cap_blocks_excess_allocation(tmp_path: Path, monkeypatch) -> None:
    env = build_rollout_env(
        tmp_path,
        monkeypatch,
        settings_update={
            "live_strategy_max_capital_pct": 50.0,
            "live_symbol_max_capital_pct": 100.0,
        },
    )
    upsert_rollout_state(env, phase="scaled", capital_limit=1000.0)
    seed_open_position(
        env,
        position_id="pos_strategy_001",
        symbol="ETHUSDT",
        strategy_name="trend_follow_continuation",
        notional_value=450.0,
    )
    assessment = build_assessment(
        assessment_id="ras_strategy_block",
        symbol="BTCUSDT",
        strategy_name="trend_follow_continuation",
        notional_value=100.0,
    )

    decision = env["rollout_service"].evaluate_trade_under_rollout(  # type: ignore[index]
        order_request=build_order_request(assessment),
        assessment=assessment,
    )

    assert decision.allowed is False
    assert "strategy_cap_exceeded" in decision.reasons


def test_symbol_cap_blocks_excess_allocation(tmp_path: Path, monkeypatch) -> None:
    env = build_rollout_env(
        tmp_path,
        monkeypatch,
        settings_update={
            "live_strategy_max_capital_pct": 100.0,
            "live_symbol_max_capital_pct": 40.0,
        },
    )
    upsert_rollout_state(env, phase="scaled", capital_limit=1000.0)
    seed_open_position(
        env,
        position_id="pos_symbol_001",
        symbol="BTCUSDT",
        strategy_name="breakout",
        notional_value=350.0,
    )
    assessment = build_assessment(
        assessment_id="ras_symbol_block",
        symbol="BTCUSDT",
        strategy_name="trend_follow_continuation",
        notional_value=100.0,
    )

    decision = env["rollout_service"].evaluate_trade_under_rollout(  # type: ignore[index]
        order_request=build_order_request(assessment),
        assessment=assessment,
    )

    assert decision.allowed is False
    assert "symbol_cap_exceeded" in decision.reasons

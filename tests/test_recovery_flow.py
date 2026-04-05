from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import get_settings
from app.execution.service import ExecutionService
from app.execution.types import Approval, Position, Trade
from app.ops.recovery import RecoveryService
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.trades_repo import TradesRepository


def _build_settings(tmp_path: Path):
    return get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'recovery_flow.db'}",
            "recovery_enabled": True,
        }
    )


def _seed_state(
    approvals_repo: ApprovalsRepository,
    trades_repo: TradesRepository,
    positions_repo: PositionsRepository,
) -> None:
    now = datetime.now(timezone.utc)
    approvals_repo.upsert_approval(
        Approval(
            approval_id="apr_recovery_001",
            assessment_id="ras_recovery_001",
            signal_id="sig_recovery_001",
            symbol="BTCUSDT",
            side="long",
            strategy_name="trend_follow_continuation",
            status="pending",
            created_at=now,
            execution_mode="paper",
        )
    )
    trades_repo.upsert_trade(
        Trade(
            trade_id="trd_recovery_001",
            approval_id="apr_recovery_001",
            assessment_id="ras_recovery_001",
            signal_id="sig_recovery_001",
            position_id="pos_recovery_001",
            symbol="BTCUSDT",
            side="long",
            strategy_name="trend_follow_continuation",
            quantity=1.0,
            execution_price=100.0,
            requested_entry_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=120.0,
            status="EXECUTED",
            execution_mode="paper",
            opened_at=now,
            updated_at=now,
        )
    )
    positions_repo.upsert_position(
        Position(
            position_id="pos_recovery_001",
            trade_id="trd_recovery_001",
            approval_id="apr_recovery_001",
            assessment_id="ras_recovery_001",
            signal_id="sig_recovery_001",
            symbol="BTCUSDT",
            side="long",
            strategy_name="trend_follow_continuation",
            initial_quantity=1.0,
            quantity_open=1.0,
            entry_price=100.0,
            current_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=120.0,
            status="open",
            opened_at=now,
            updated_at=now,
            execution_mode="paper",
        )
    )


def test_recovery_rebuilds_open_positions_without_duplicates(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    approvals_repo = ApprovalsRepository(session_factory)
    trades_repo = TradesRepository(session_factory)
    positions_repo = PositionsRepository(session_factory)
    events_repo = EventsRepository(session_factory)
    _seed_state(approvals_repo, trades_repo, positions_repo)

    service = ExecutionService(
        settings=settings,
        approvals_repo=approvals_repo,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        events_repo=events_repo,
        persistence_session_factory=session_factory,
    )
    recovery = RecoveryService(
        settings=settings,
        execution_service=service,
        approvals_repo=approvals_repo,
        positions_repo=positions_repo,
        events_repo=events_repo,
    )

    first = asyncio.run(recovery.run_manual_recovery())
    second = asyncio.run(recovery.run_manual_recovery())
    positions = asyncio.run(service.get_positions())

    assert first.ok is True
    assert second.ok is True
    assert first.open_positions_rebuilt == 1
    assert second.open_positions_rebuilt == 1
    assert len(positions) == 1


def test_recovery_persists_event_log(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    approvals_repo = ApprovalsRepository(session_factory)
    trades_repo = TradesRepository(session_factory)
    positions_repo = PositionsRepository(session_factory)
    events_repo = EventsRepository(session_factory)
    _seed_state(approvals_repo, trades_repo, positions_repo)

    service = ExecutionService(
        settings=settings,
        approvals_repo=approvals_repo,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        events_repo=events_repo,
        persistence_session_factory=session_factory,
    )
    recovery = RecoveryService(
        settings=settings,
        execution_service=service,
        approvals_repo=approvals_repo,
        positions_repo=positions_repo,
        events_repo=events_repo,
    )

    asyncio.run(recovery.run_manual_recovery())
    events = events_repo.list_recent_events(limit=10, execution_mode="ops")

    event_types = {item["event_type"] for item in events}
    assert "manual_recovery_started" in event_types
    assert "manual_recovery_completed" in event_types

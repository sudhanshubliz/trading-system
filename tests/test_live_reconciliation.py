from __future__ import annotations

from datetime import datetime, timezone

from app.config.settings import get_settings
from app.execution.types import Position, Trade
from app.live.locks import LiveLockManager
from app.live.reconciler import LiveReconciler
from app.live.types import LiveLockType
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.locks_repo import LocksRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.trades_repo import TradesRepository


class EmptySyncService:
    def get_open_orders(self):
        return []

    def get_positions(self):
        return []


def test_live_execute_blocked_by_active_lock(tmp_path) -> None:
    settings = get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'live_reconcile_block.db'}",
        }
    )
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    locks_repo = LocksRepository(session_factory)
    manager = LiveLockManager(locks_repo=locks_repo)

    lock = manager.activate_lock(LiveLockType.EXCHANGE_SYNC_ERROR, reason="exchange_sync_error")
    allowed, active_locks = manager.is_live_execution_allowed()

    assert allowed is False
    assert any(item.lock_id == lock.lock_id for item in active_locks)


def test_reconciliation_mismatch_activates_lock(tmp_path) -> None:
    settings = get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'live_reconcile.db'}",
        }
    )
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    trades_repo = TradesRepository(session_factory)
    positions_repo = PositionsRepository(session_factory)
    locks_repo = LocksRepository(session_factory)
    events_repo = EventsRepository(session_factory)

    now = datetime.now(timezone.utc)
    trades_repo.upsert_trade(
        Trade(
            trade_id="trd_live_001",
            approval_id="apr_live_001",
            assessment_id="ras_live_001",
            signal_id="sig_live_001",
            position_id="pos_live_001",
            symbol="BTCUSDT",
            side="long",
            strategy_name="trend_follow_continuation",
            quantity=1.0,
            execution_price=100.0,
            requested_entry_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=120.0,
            status="FILLED",
            execution_mode="live",
            opened_at=now,
            updated_at=now,
            exchange_order_id="999",
            exchange_status="FILLED",
            reconciliation_status="pending",
        )
    )
    positions_repo.upsert_position(
        Position(
            position_id="pos_live_001",
            trade_id="trd_live_001",
            approval_id="apr_live_001",
            assessment_id="ras_live_001",
            signal_id="sig_live_001",
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
            execution_mode="live",
            reconciliation_status="pending",
        )
    )

    manager = LiveLockManager(locks_repo=locks_repo, events_repo=events_repo)
    reconciler = LiveReconciler(
        live_sync=EmptySyncService(),
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        lock_manager=manager,
        events_repo=events_repo,
    )

    result = reconciler.reconcile()
    active = locks_repo.list_active_locks()
    events = events_repo.list_events(execution_mode="live")

    assert result.ok is False
    assert result.activated_lock_id is not None
    assert any(lock.lock_type == LiveLockType.EXCHANGE_SYNC_ERROR for lock in active)
    assert any(event["event_type"] == "live_reconciliation_mismatch" for event in events)

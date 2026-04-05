from __future__ import annotations

from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.locks_repo import LocksRepository
from app.live.locks import LiveLockManager
from app.live.types import LiveLockType
from app.config.settings import get_settings


def test_lock_activation_and_clear_persist(tmp_path) -> None:
    settings = get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'live_locks.db'}",
        }
    )
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    locks_repo = LocksRepository(session_factory)
    events_repo = EventsRepository(session_factory)
    manager = LiveLockManager(locks_repo=locks_repo, events_repo=events_repo)

    lock = manager.activate_lock(
        LiveLockType.EXCHANGE_SYNC_ERROR,
        reason="sync_failed",
        metadata={"attempt": 1},
    )
    persisted_active = locks_repo.get_lock(lock.lock_id)
    cleared = manager.clear_lock(lock.lock_id, reason="manual_clear")
    persisted_cleared = locks_repo.get_lock(lock.lock_id)
    events = events_repo.list_events(execution_mode="live")

    assert persisted_active is not None
    assert persisted_active.is_active is True
    assert cleared is not None
    assert persisted_cleared is not None
    assert persisted_cleared.is_active is False
    assert any(event["event_type"] == "live_lock_activated" for event in events)
    assert any(event["event_type"] == "live_lock_cleared" for event in events)

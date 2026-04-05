from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict
from datetime import datetime, timezone

from app.core.logging import log_structured_event
from app.live.types import LiveRiskLock
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.locks_repo import LocksRepository

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveLockManager:
    def __init__(
        self,
        *,
        locks_repo: LocksRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.locks_repo = locks_repo
        self.events_repo = events_repo
        self._locks: dict[str, LiveRiskLock] = {}
        self.recover()

    def recover(self) -> None:
        self._locks = {}
        if self.locks_repo is None:
            return
        for lock in self.locks_repo.list_locks():
            self._locks[lock.lock_id] = lock

    def activate_lock(
        self,
        lock_type: str,
        *,
        reason: str,
        metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> LiveRiskLock:
        lock_id = self._build_lock_id(lock_type)
        now = utc_now()
        existing = self._locks.get(lock_id)
        lock = LiveRiskLock(
            lock_id=lock_id,
            lock_type=lock_type,
            is_active=True,
            reason=reason,
            activated_at=existing.activated_at if existing is not None else now,
            cleared_at=None,
            metadata=metadata or {},
        )
        self._locks[lock_id] = lock
        if self.locks_repo is not None:
            self.locks_repo.upsert_lock(lock)
        self._append_event("live_lock_activated", lock)
        return lock

    def clear_lock(self, lock_id: str, *, reason: str | None = None) -> LiveRiskLock | None:
        lock = self._locks.get(lock_id)
        if lock is None:
            if self.locks_repo is not None:
                lock = self.locks_repo.get_lock(lock_id)
            if lock is None:
                return None

        lock = LiveRiskLock(
            lock_id=lock.lock_id,
            lock_type=lock.lock_type,
            is_active=False,
            reason=reason or lock.reason,
            activated_at=lock.activated_at,
            cleared_at=utc_now(),
            metadata=lock.metadata,
        )
        self._locks[lock.lock_id] = lock
        if self.locks_repo is not None:
            self.locks_repo.clear_lock(lock.lock_id, cleared_at=lock.cleared_at, reason=lock.reason)
        self._append_event("live_lock_cleared", lock)
        return lock

    def list_locks(self, *, active_only: bool = False) -> list[LiveRiskLock]:
        items = list(self._locks.values())
        items.sort(key=lambda item: item.activated_at, reverse=True)
        if active_only:
            items = [item for item in items if item.is_active]
        return items

    def list_active_locks(self) -> list[LiveRiskLock]:
        return self.list_locks(active_only=True)

    def is_live_execution_allowed(self) -> tuple[bool, list[LiveRiskLock]]:
        active_locks = self.list_active_locks()
        return (len(active_locks) == 0, active_locks)

    def _build_lock_id(self, lock_type: str) -> str:
        digest = hashlib.sha1(lock_type.encode("utf-8")).hexdigest()
        return f"lck_{digest[:12]}"

    def _append_event(self, event_type: str, lock: LiveRiskLock) -> None:
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type=event_type,
                entity_id=lock.lock_id,
                execution_mode="live",
                payload=asdict(lock),
            )
        log_structured_event(
            logger,
            event_type,
            lock_id=lock.lock_id,
            lock_type=lock.lock_type,
            is_active=lock.is_active,
            reason=lock.reason,
        )

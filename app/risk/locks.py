from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.persistence.repositories.events_repo import EventsRepository

if TYPE_CHECKING:
    from app.persistence.repositories.risk_lock_events_repo import RiskLockEventsRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class RiskLockEvent:
    event_id: str
    lock_key: str
    lock_type: str
    scope: str
    scope_key: str
    severity: str
    reason: str
    metrics_snapshot: dict[str, object] = field(default_factory=dict)
    is_active: bool = True
    triggered_at: datetime | None = None
    released_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class RiskLockManager:
    def __init__(
        self,
        *,
        repo: "RiskLockEventsRepository | None" = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.repo = repo
        self.events_repo = events_repo
        self._active: dict[str, RiskLockEvent] = {}
        self._history: OrderedDict[str, RiskLockEvent] = OrderedDict()
        self.recover()

    def recover(self) -> None:
        self._active = {}
        if self.repo is None:
            return
        for item in self.repo.list_current():
            self._active[item.lock_key] = item
            self._history[item.event_id] = item

    def activate(
        self,
        *,
        lock_type: str,
        scope: str,
        scope_key: str,
        severity: str,
        reason: str,
        metrics_snapshot: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> RiskLockEvent:
        now = utc_now()
        lock_key = self._build_lock_key(lock_type=lock_type, scope=scope, scope_key=scope_key)
        existing = self._active.get(lock_key)
        event = RiskLockEvent(
            event_id=self._build_event_id(lock_key, now),
            lock_key=lock_key,
            lock_type=lock_type,
            scope=scope,
            scope_key=scope_key,
            severity=severity,
            reason=reason,
            metrics_snapshot=metrics_snapshot or {},
            is_active=True,
            triggered_at=existing.triggered_at if existing is not None else now,
            released_at=None,
            metadata=metadata or {},
        )
        self._active[lock_key] = event
        self._remember(event)
        if self.repo is not None:
            self.repo.append_event(event)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="risk_lock_activated",
                entity_id=event.event_id,
                symbol=scope_key if scope == "symbol" else None,
                payload={
                    "lock_type": event.lock_type,
                    "scope": event.scope,
                    "scope_key": event.scope_key,
                    "severity": event.severity,
                    "reason": event.reason,
                },
            )
        return event

    def clear(self, *, lock_type: str, scope: str, scope_key: str, reason: str) -> RiskLockEvent | None:
        lock_key = self._build_lock_key(lock_type=lock_type, scope=scope, scope_key=scope_key)
        existing = self._active.get(lock_key)
        if existing is None:
            return None
        cleared = RiskLockEvent(
            event_id=self._build_event_id(lock_key, utc_now()),
            lock_key=lock_key,
            lock_type=existing.lock_type,
            scope=existing.scope,
            scope_key=existing.scope_key,
            severity=existing.severity,
            reason=reason,
            metrics_snapshot=existing.metrics_snapshot,
            is_active=False,
            triggered_at=existing.triggered_at,
            released_at=utc_now(),
            metadata=existing.metadata,
        )
        self._active.pop(lock_key, None)
        self._remember(cleared)
        if self.repo is not None:
            self.repo.append_event(cleared)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="risk_lock_cleared",
                entity_id=cleared.event_id,
                symbol=scope_key if scope == "symbol" else None,
                payload={"lock_type": cleared.lock_type, "scope": cleared.scope, "scope_key": cleared.scope_key},
            )
        return cleared

    def list_current(self) -> list[RiskLockEvent]:
        return sorted(self._active.values(), key=lambda item: item.triggered_at or utc_now(), reverse=True)

    def list_history(self, *, limit: int = 100) -> list[RiskLockEvent]:
        if self.repo is None:
            return list(self._history.values())[:limit]
        return self.repo.list_history(limit=limit)

    def _remember(self, event: RiskLockEvent) -> None:
        self._history[event.event_id] = event
        self._history.move_to_end(event.event_id, last=False)
        while len(self._history) > 500:
            self._history.popitem(last=True)

    def _build_lock_key(self, *, lock_type: str, scope: str, scope_key: str) -> str:
        return f"{lock_type}:{scope}:{scope_key}"

    def _build_event_id(self, lock_key: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{lock_key}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"rlock_{digest[:12]}"

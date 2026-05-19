from __future__ import annotations

from collections import OrderedDict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import RiskLockEventRecord
from app.risk.locks import RiskLockEvent


class RiskLockEventsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def append_event(self, event: RiskLockEvent, *, session: Session | None = None) -> RiskLockEvent:
        return self._with_session(session, lambda db: self._append(db, event))

    def list_history(self, *, limit: int = 100, session: Session | None = None) -> list[RiskLockEvent]:
        return self._with_session(session, lambda db: self._list_history(db, limit=limit)) or []

    def list_current(self, *, session: Session | None = None) -> list[RiskLockEvent]:
        return self._with_session(session, self._list_current) or []

    def _append(self, session: Session, event: RiskLockEvent) -> RiskLockEvent:
        session.add(
            RiskLockEventRecord(
                event_id=event.event_id,
                lock_type=event.lock_type,
                severity=event.severity,
                is_active="true" if event.is_active else "false",
                observed_at=event.released_at or event.triggered_at,
                payload_json=serialize_payload(event),
            )
        )
        return event

    def _list_history(self, session: Session, *, limit: int) -> list[RiskLockEvent]:
        query = select(RiskLockEventRecord).order_by(RiskLockEventRecord.observed_at.desc()).limit(max(limit, 0))
        return [self._deserialize(record.payload_json) for record in session.scalars(query).all()]

    def _list_current(self, session: Session) -> list[RiskLockEvent]:
        query = select(RiskLockEventRecord).order_by(RiskLockEventRecord.observed_at.desc())
        latest_by_key: OrderedDict[str, RiskLockEvent] = OrderedDict()
        for record in session.scalars(query).all():
            event = self._deserialize(record.payload_json)
            if event.lock_key in latest_by_key:
                continue
            latest_by_key[event.lock_key] = event
        return [item for item in latest_by_key.values() if item.is_active]

    def _deserialize(self, payload_json: str) -> RiskLockEvent:
        payload = deserialize_payload(payload_json)
        payload["triggered_at"] = ensure_aware_datetime(payload.get("triggered_at"))
        payload["released_at"] = ensure_aware_datetime(payload.get("released_at"))
        return RiskLockEvent(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

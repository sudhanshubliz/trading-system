from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.live.types import LiveRiskLock
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import LiveLockRecord


class LocksRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_lock(self, lock: LiveRiskLock, *, session: Session | None = None) -> LiveRiskLock:
        return self._with_session(session, lambda db: self._upsert(db, lock))

    def list_active_locks(self, *, session: Session | None = None) -> list[LiveRiskLock]:
        return self._with_session(session, self._list_active) or []

    def list_locks(self, *, session: Session | None = None) -> list[LiveRiskLock]:
        return self._with_session(session, self._list_all) or []

    def get_lock(self, lock_id: str, *, session: Session | None = None) -> LiveRiskLock | None:
        return self._with_session(session, lambda db: self._get(db, lock_id))

    def clear_lock(
        self,
        lock_id: str,
        *,
        cleared_at,
        reason: str,
        session: Session | None = None,
    ) -> LiveRiskLock | None:
        return self._with_session(session, lambda db: self._clear(db, lock_id, cleared_at=cleared_at, reason=reason))

    def _upsert(self, session: Session, lock: LiveRiskLock) -> LiveRiskLock:
        record = session.get(LiveLockRecord, lock.lock_id)
        payload = asdict(lock)
        if record is None:
            record = LiveLockRecord(
                lock_id=lock.lock_id,
                lock_type=lock.lock_type,
                is_active="true" if lock.is_active else "false",
                reason=lock.reason,
                activated_at=lock.activated_at,
                cleared_at=lock.cleared_at,
                payload_json=serialize_payload(payload),
            )
            session.add(record)
        else:
            record.lock_type = lock.lock_type
            record.is_active = "true" if lock.is_active else "false"
            record.reason = lock.reason
            record.activated_at = lock.activated_at
            record.cleared_at = lock.cleared_at
            record.payload_json = serialize_payload(payload)
        return lock

    def _list_active(self, session: Session) -> list[LiveRiskLock]:
        query = select(LiveLockRecord).where(LiveLockRecord.is_active == "true").order_by(LiveLockRecord.activated_at.desc())
        return [self._to_lock(item) for item in session.scalars(query).all()]

    def _list_all(self, session: Session) -> list[LiveRiskLock]:
        query = select(LiveLockRecord).order_by(LiveLockRecord.activated_at.desc())
        return [self._to_lock(item) for item in session.scalars(query).all()]

    def _get(self, session: Session, lock_id: str) -> LiveRiskLock | None:
        record = session.get(LiveLockRecord, lock_id)
        if record is None:
            return None
        return self._to_lock(record)

    def _clear(self, session: Session, lock_id: str, *, cleared_at, reason: str) -> LiveRiskLock | None:
        record = session.get(LiveLockRecord, lock_id)
        if record is None:
            return None
        payload = deserialize_payload(record.payload_json)
        payload["is_active"] = False
        payload["cleared_at"] = cleared_at
        payload["reason"] = reason
        record.is_active = "false"
        record.cleared_at = cleared_at
        record.reason = reason
        record.payload_json = serialize_payload(payload)
        return self._to_lock(record)

    def _to_lock(self, record: LiveLockRecord) -> LiveRiskLock:
        payload = deserialize_payload(record.payload_json)
        payload["activated_at"] = ensure_aware_datetime(payload.get("activated_at"))
        payload["cleared_at"] = ensure_aware_datetime(payload.get("cleared_at"))
        payload["is_active"] = record.is_active == "true"
        return LiveRiskLock(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], LiveRiskLock | list[LiveRiskLock] | None]) -> LiveRiskLock | list[LiveRiskLock] | None:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

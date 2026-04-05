from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, serialize_payload, utc_now
from app.persistence.models import EventRecord


class EventsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def append_event(
        self,
        *,
        event_type: str,
        entity_id: str | None = None,
        trade_id: str | None = None,
        symbol: str | None = None,
        execution_mode: str | None = None,
        payload: dict[str, Any] | None = None,
        session: Session | None = None,
    ) -> dict[str, Any]:
        return self._with_session(
            session,
            lambda db: self._append(
                db,
                event_type=event_type,
                entity_id=entity_id,
                trade_id=trade_id,
                symbol=symbol,
                execution_mode=execution_mode,
                payload=payload or {},
            ),
        )

    def list_events(
        self,
        *,
        event_type: str | None = None,
        entity_id: str | None = None,
        trade_id: str | None = None,
        execution_mode: str | None = None,
        session: Session | None = None,
    ) -> list[dict[str, Any]]:
        return self._with_session(session, lambda db: self._list(db, event_type=event_type, entity_id=entity_id, trade_id=trade_id, execution_mode=execution_mode)) or []

    def list_recent_events(
        self,
        *,
        limit: int = 100,
        execution_mode: str | None = None,
        session: Session | None = None,
    ) -> list[dict[str, Any]]:
        return self._with_session(
            session,
            lambda db: self._list_recent(db, limit=limit, execution_mode=execution_mode),
        ) or []

    def list_critical_events(
        self,
        *,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[dict[str, Any]]:
        return self._with_session(session, lambda db: self._list_critical(db, limit=limit)) or []

    def _append(
        self,
        session: Session,
        *,
        event_type: str,
        entity_id: str | None,
        trade_id: str | None,
        symbol: str | None,
        execution_mode: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp = utc_now()
        event_payload = {
            "event_type": event_type,
            "entity_id": entity_id,
            "trade_id": trade_id,
            "symbol": symbol,
            "execution_mode": execution_mode,
            "timestamp": timestamp,
            "payload": payload,
        }
        record = EventRecord(
            event_type=event_type,
            entity_id=entity_id,
            trade_id=trade_id,
            symbol=symbol,
            execution_mode=execution_mode,
            timestamp=timestamp,
            payload_json=serialize_payload(event_payload),
        )
        session.add(record)
        return event_payload

    def _list(self, session: Session, *, event_type: str | None, entity_id: str | None, trade_id: str | None, execution_mode: str | None) -> list[dict[str, Any]]:
        query = select(EventRecord)
        if event_type is not None:
            query = query.where(EventRecord.event_type == event_type)
        if entity_id is not None:
            query = query.where(EventRecord.entity_id == entity_id)
        if trade_id is not None:
            query = query.where(EventRecord.trade_id == trade_id)
        if execution_mode is not None:
            query = query.where(EventRecord.execution_mode == execution_mode)
        query = query.order_by(EventRecord.timestamp.desc())
        return [deserialize_payload(record.payload_json) for record in session.scalars(query).all()]

    def _list_recent(self, session: Session, *, limit: int, execution_mode: str | None) -> list[dict[str, Any]]:
        query = select(EventRecord)
        if execution_mode is not None:
            query = query.where(EventRecord.execution_mode == execution_mode)
        query = query.order_by(EventRecord.timestamp.desc()).limit(max(limit, 0))
        return [deserialize_payload(record.payload_json) for record in session.scalars(query).all()]

    def _list_critical(self, session: Session, *, limit: int) -> list[dict[str, Any]]:
        critical_types = (
            "live_order_rejected",
            "live_reconciliation_mismatch",
            "live_lock_activated",
            "startup_recovery_failed",
            "manual_recovery_failed",
            "startup_preflight_failed",
            "incident_detected",
            "rollout_auto_rollback",
            "rollout_manual_rollback",
        )
        query = (
            select(EventRecord)
            .where(EventRecord.event_type.in_(critical_types))
            .order_by(EventRecord.timestamp.desc())
            .limit(max(limit, 0))
        )
        return [deserialize_payload(record.payload_json) for record in session.scalars(query).all()]

    def _with_session(self, session: Session | None, callback: Callable[[Session], Any]) -> Any:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import PortfolioRecord


class PortfolioRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def append_record(
        self,
        *,
        record_type: str,
        scope_key: str,
        execution_mode: str,
        payload: dict[str, Any],
        session: Session | None = None,
    ) -> str:
        return self._with_session(
            session,
            lambda db: self._append(
                db,
                record_type=record_type,
                scope_key=scope_key,
                execution_mode=execution_mode,
                payload=payload,
            ),
        )

    def list_records(
        self,
        *,
        record_type: str | None = None,
        execution_mode: str | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[dict[str, Any]]:
        return self._with_session(
            session,
            lambda db: self._list(db, record_type=record_type, execution_mode=execution_mode, limit=limit),
        ) or []

    def _append(
        self,
        session: Session,
        *,
        record_type: str,
        scope_key: str,
        execution_mode: str,
        payload: dict[str, Any],
    ) -> str:
        record_id = f"port_{uuid4().hex[:20]}"
        timestamp = utc_now()
        session.add(
            PortfolioRecord(
                record_id=record_id,
                record_type=record_type,
                scope_key=scope_key,
                execution_mode=execution_mode,
                created_at=timestamp,
                payload_json=serialize_payload(
                    {
                        "record_id": record_id,
                        "record_type": record_type,
                        "scope_key": scope_key,
                        "execution_mode": execution_mode,
                        "created_at": timestamp,
                        "payload": payload,
                    }
                ),
            )
        )
        return record_id

    def _list(
        self,
        session: Session,
        *,
        record_type: str | None,
        execution_mode: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        query = select(PortfolioRecord)
        if record_type is not None:
            query = query.where(PortfolioRecord.record_type == record_type)
        if execution_mode is not None:
            query = query.where(PortfolioRecord.execution_mode == execution_mode)
        query = query.order_by(PortfolioRecord.created_at.desc()).limit(max(limit, 0))
        items: list[dict[str, Any]] = []
        for record in session.scalars(query).all():
            payload = deserialize_payload(record.payload_json)
            payload["created_at"] = ensure_aware_datetime(payload.get("created_at"))
            items.append(payload)
        return items

    def _with_session(self, session: Session | None, callback: Callable[[Session], Any]) -> Any:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

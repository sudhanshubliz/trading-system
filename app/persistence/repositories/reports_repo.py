from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, serialize_payload, utc_now
from app.persistence.models import ReportRecord


class ReportsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_report(
        self,
        *,
        report_id: str,
        scope: str,
        scope_key: str,
        generated_at,
        payload: dict[str, Any],
        session: Session | None = None,
    ) -> dict[str, Any]:
        return self._with_session(
            session,
            lambda db: self._upsert(db, report_id=report_id, scope=scope, scope_key=scope_key, generated_at=generated_at, payload=payload),
        )

    def get_report(self, report_id: str, *, session: Session | None = None) -> dict[str, Any] | None:
        return self._with_session(session, lambda db: self._get(db, report_id))

    def list_reports(self, scope: str | None = None, *, session: Session | None = None) -> list[dict[str, Any]]:
        return self._with_session(session, lambda db: self._list(db, scope)) or []

    def _upsert(self, session: Session, *, report_id: str, scope: str, scope_key: str, generated_at, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        record = session.get(ReportRecord, report_id)
        if record is None:
            record = ReportRecord(
                report_id=report_id,
                scope=scope,
                scope_key=scope_key,
                generated_at=generated_at,
                payload_json=serialize_payload(payload),
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.scope = scope
            record.scope_key = scope_key
            record.generated_at = generated_at
            record.payload_json = serialize_payload(payload)
            record.updated_at = now
        return payload

    def _get(self, session: Session, report_id: str) -> dict[str, Any] | None:
        record = session.get(ReportRecord, report_id)
        if record is None:
            return None
        return deserialize_payload(record.payload_json)

    def _list(self, session: Session, scope: str | None) -> list[dict[str, Any]]:
        query = select(ReportRecord)
        if scope is not None:
            query = query.where(ReportRecord.scope == scope)
        query = query.order_by(ReportRecord.generated_at.desc())
        return [deserialize_payload(record.payload_json) for record in session.scalars(query).all()]

    def _with_session(self, session: Session | None, callback: Callable[[Session], Any]) -> Any:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import AnalyticsRecord


class AnalyticsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_report(
        self,
        *,
        report_type: str,
        scope_key: str,
        execution_mode: str | None,
        payload: dict[str, Any],
        session: Session | None = None,
    ) -> str:
        return self._with_session(
            session,
            lambda db: self._upsert(
                db,
                report_type=report_type,
                scope_key=scope_key,
                execution_mode=execution_mode,
                payload=payload,
            ),
        )

    def list_reports(
        self,
        *,
        report_type: str | None = None,
        execution_mode: str | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[dict[str, Any]]:
        return self._with_session(
            session,
            lambda db: self._list(db, report_type=report_type, execution_mode=execution_mode, limit=limit),
        ) or []

    def _upsert(
        self,
        session: Session,
        *,
        report_type: str,
        scope_key: str,
        execution_mode: str | None,
        payload: dict[str, Any],
    ) -> str:
        report_id = f"{report_type}:{scope_key}:{execution_mode or 'all'}"
        generated_at = utc_now()
        record = session.get(AnalyticsRecord, report_id)
        serialized = serialize_payload(
            {
                "report_id": report_id,
                "report_type": report_type,
                "scope_key": scope_key,
                "execution_mode": execution_mode,
                "generated_at": generated_at,
                "payload": payload,
            }
        )
        if record is None:
            record = AnalyticsRecord(
                report_id=report_id,
                report_type=report_type,
                scope_key=scope_key,
                execution_mode=execution_mode,
                generated_at=generated_at,
                payload_json=serialized,
            )
            session.add(record)
        else:
            record.report_type = report_type
            record.scope_key = scope_key
            record.execution_mode = execution_mode
            record.generated_at = generated_at
            record.payload_json = serialized
        return report_id

    def _list(
        self,
        session: Session,
        *,
        report_type: str | None,
        execution_mode: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        query = select(AnalyticsRecord)
        if report_type is not None:
            query = query.where(AnalyticsRecord.report_type == report_type)
        if execution_mode is not None:
            query = query.where(AnalyticsRecord.execution_mode == execution_mode)
        query = query.order_by(AnalyticsRecord.generated_at.desc()).limit(max(limit, 0))
        items: list[dict[str, Any]] = []
        for record in session.scalars(query).all():
            payload = deserialize_payload(record.payload_json)
            payload["generated_at"] = ensure_aware_datetime(payload.get("generated_at"))
            items.append(payload)
        return items

    def _with_session(self, session: Session | None, callback: Callable[[Session], Any]) -> Any:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import AlertHistoryRecord, IncidentRecord, OperatorNoteRecord


class SystemRecordsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def append_alert(self, payload: dict[str, object], *, session: Session | None = None) -> dict[str, object]:
        return self._with_session(session, lambda db: self._append_alert(db, payload))

    def append_operator_note(self, payload: dict[str, object], *, session: Session | None = None) -> dict[str, object]:
        return self._with_session(session, lambda db: self._append_operator_note(db, payload))

    def append_incident(self, payload: dict[str, object], *, session: Session | None = None) -> dict[str, object]:
        return self._with_session(session, lambda db: self._append_incident(db, payload))

    def get_incident(self, incident_id: str, *, session: Session | None = None) -> dict[str, object] | None:
        return self._with_session(session, lambda db: self._get_incident(db, incident_id))

    def update_incident(self, incident_id: str, payload: dict[str, object], *, session: Session | None = None) -> dict[str, object] | None:
        return self._with_session(session, lambda db: self._update_incident(db, incident_id, payload))

    def list_alerts(self, *, limit: int = 100, session: Session | None = None) -> list[dict[str, object]]:
        return self._with_session(session, lambda db: self._list_alerts(db, limit=limit)) or []

    def list_operator_notes(self, *, limit: int = 100, session: Session | None = None) -> list[dict[str, object]]:
        return self._with_session(session, lambda db: self._list_notes(db, limit=limit)) or []

    def list_incidents(self, *, limit: int = 100, session: Session | None = None) -> list[dict[str, object]]:
        return self._with_session(session, lambda db: self._list_incidents(db, limit=limit)) or []

    def _append_alert(self, session: Session, payload: dict[str, object]) -> dict[str, object]:
        session.add(
            AlertHistoryRecord(
                alert_id=str(payload["alert_id"]),
                channel=str(payload.get("channel", "openclaw")),
                severity=str(payload.get("severity", "info")),
                created_at=ensure_aware_datetime(payload.get("created_at")),
                payload_json=serialize_payload(payload),
            )
        )
        return payload

    def _append_operator_note(self, session: Session, payload: dict[str, object]) -> dict[str, object]:
        session.add(
            OperatorNoteRecord(
                note_id=str(payload["note_id"]),
                note_type=str(payload.get("note_type", "general")),
                related_entity_id=str(payload.get("related_entity_id")) if payload.get("related_entity_id") is not None else None,
                created_at=ensure_aware_datetime(payload.get("created_at")),
                payload_json=serialize_payload(payload),
            )
        )
        return payload

    def _append_incident(self, session: Session, payload: dict[str, object]) -> dict[str, object]:
        session.add(
            IncidentRecord(
                incident_id=str(payload["incident_id"]),
                category=str(payload.get("category")) if payload.get("category") is not None else None,
                severity=str(payload.get("severity", "medium")),
                source=str(payload.get("source")) if payload.get("source") is not None else None,
                status=str(payload.get("status", "open")),
                impacted_scope=str(payload.get("impacted_scope")) if payload.get("impacted_scope") is not None else None,
                related_provider=str(payload.get("related_provider")) if payload.get("related_provider") is not None else None,
                related_strategy=str(payload.get("related_strategy")) if payload.get("related_strategy") is not None else None,
                related_symbol_or_market=str(payload.get("related_symbol_or_market")) if payload.get("related_symbol_or_market") is not None else None,
                created_at=ensure_aware_datetime(payload.get("created_at")),
                acknowledged_at=ensure_aware_datetime(payload.get("acknowledged_at")),
                resolved_at=ensure_aware_datetime(payload.get("resolved_at")),
                updated_at=ensure_aware_datetime(payload.get("updated_at")),
                payload_json=serialize_payload(payload),
            )
        )
        return payload

    def _get_incident(self, session: Session, incident_id: str) -> dict[str, object] | None:
        record = session.get(IncidentRecord, incident_id)
        return deserialize_payload(record.payload_json) if record is not None else None

    def _update_incident(self, session: Session, incident_id: str, payload: dict[str, object]) -> dict[str, object] | None:
        record = session.get(IncidentRecord, incident_id)
        if record is None:
            return None
        merged = {**deserialize_payload(record.payload_json), **payload}
        record.category = str(merged.get("category")) if merged.get("category") is not None else None
        record.severity = str(merged.get("severity", record.severity))
        record.source = str(merged.get("source")) if merged.get("source") is not None else None
        record.status = str(merged.get("status", record.status))
        record.impacted_scope = str(merged.get("impacted_scope")) if merged.get("impacted_scope") is not None else None
        record.related_provider = str(merged.get("related_provider")) if merged.get("related_provider") is not None else None
        record.related_strategy = str(merged.get("related_strategy")) if merged.get("related_strategy") is not None else None
        record.related_symbol_or_market = str(merged.get("related_symbol_or_market")) if merged.get("related_symbol_or_market") is not None else None
        record.acknowledged_at = ensure_aware_datetime(merged.get("acknowledged_at"))
        record.resolved_at = ensure_aware_datetime(merged.get("resolved_at"))
        record.updated_at = ensure_aware_datetime(merged.get("updated_at")) or ensure_aware_datetime(payload.get("updated_at")) or record.updated_at
        record.payload_json = serialize_payload(merged)
        return merged

    def _list_alerts(self, session: Session, *, limit: int) -> list[dict[str, object]]:
        query = select(AlertHistoryRecord).order_by(AlertHistoryRecord.created_at.desc()).limit(max(limit, 0))
        return [deserialize_payload(record.payload_json) for record in session.scalars(query).all()]

    def _list_notes(self, session: Session, *, limit: int) -> list[dict[str, object]]:
        query = select(OperatorNoteRecord).order_by(OperatorNoteRecord.created_at.desc()).limit(max(limit, 0))
        return [deserialize_payload(record.payload_json) for record in session.scalars(query).all()]

    def _list_incidents(self, session: Session, *, limit: int) -> list[dict[str, object]]:
        query = select(IncidentRecord).order_by(IncidentRecord.created_at.desc()).limit(max(limit, 0))
        return [deserialize_payload(record.payload_json) for record in session.scalars(query).all()]

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

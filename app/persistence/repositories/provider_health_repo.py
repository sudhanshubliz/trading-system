from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import ProviderHealthEventRecord, ProviderHealthSnapshotRecord, ProviderIngestRunRecord
from app.provider_health.types import ProviderHealthSnapshot, ProviderIngestRun


class ProviderHealthRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_snapshot(self, snapshot: ProviderHealthSnapshot, *, session: Session | None = None) -> ProviderHealthSnapshot:
        return self._with_session(session, lambda db: self._upsert(db, snapshot))

    def append_event(self, snapshot: ProviderHealthSnapshot, *, session: Session | None = None) -> ProviderHealthSnapshot:
        return self._with_session(session, lambda db: self._append_event(db, snapshot))

    def get_latest(self, provider_name: str, *, session: Session | None = None) -> ProviderHealthSnapshot | None:
        return self._with_session(session, lambda db: self._get_latest(db, provider_name))

    def list_latest(self, *, session: Session | None = None) -> list[ProviderHealthSnapshot]:
        return self._with_session(session, self._list_latest) or []

    def list_events(self, *, provider_name: str | None = None, limit: int = 100, session: Session | None = None) -> list[ProviderHealthSnapshot]:
        return self._with_session(session, lambda db: self._list_events(db, provider_name=provider_name, limit=limit)) or []

    def upsert_ingest_run(self, item: ProviderIngestRun, *, session: Session | None = None) -> ProviderIngestRun:
        return self._with_session(session, lambda db: self._upsert_ingest_run(db, item))

    def list_ingest_runs(self, *, provider_name: str | None = None, limit: int = 100, session: Session | None = None) -> list[ProviderIngestRun]:
        return self._with_session(session, lambda db: self._list_ingest_runs(db, provider_name=provider_name, limit=limit)) or []

    def _upsert(self, session: Session, snapshot: ProviderHealthSnapshot) -> ProviderHealthSnapshot:
        record = session.get(ProviderHealthSnapshotRecord, snapshot.snapshot_id)
        payload = serialize_payload(snapshot)
        if record is None:
            session.add(
                ProviderHealthSnapshotRecord(
                    snapshot_id=snapshot.snapshot_id,
                    provider_name=snapshot.provider_name,
                    status=snapshot.status,
                    observed_at=snapshot.observed_at,
                    payload_json=payload,
                )
            )
        else:
            record.provider_name = snapshot.provider_name
            record.status = snapshot.status
            record.observed_at = snapshot.observed_at
            record.payload_json = payload
        return snapshot

    def _append_event(self, session: Session, snapshot: ProviderHealthSnapshot) -> ProviderHealthSnapshot:
        session.add(
            ProviderHealthEventRecord(
                event_id=f"phev_{snapshot.snapshot_id}",
                provider_name=snapshot.provider_name,
                severity="high" if snapshot.status == "unhealthy" else "medium" if snapshot.status == "degraded" else "low",
                status=snapshot.status,
                observed_at=snapshot.observed_at,
                payload_json=serialize_payload(snapshot),
            )
        )
        return snapshot

    def _get_latest(self, session: Session, provider_name: str) -> ProviderHealthSnapshot | None:
        query = (
            select(ProviderHealthSnapshotRecord)
            .where(ProviderHealthSnapshotRecord.provider_name == provider_name)
            .order_by(ProviderHealthSnapshotRecord.observed_at.desc())
            .limit(1)
        )
        record = session.scalar(query)
        return self._deserialize(record.payload_json) if record is not None else None

    def _list_latest(self, session: Session) -> list[ProviderHealthSnapshot]:
        query = select(ProviderHealthSnapshotRecord).order_by(ProviderHealthSnapshotRecord.observed_at.desc())
        seen: set[str] = set()
        items: list[ProviderHealthSnapshot] = []
        for record in session.scalars(query).all():
            if record.provider_name in seen:
                continue
            seen.add(record.provider_name)
            items.append(self._deserialize(record.payload_json))
        return items

    def _list_events(self, session: Session, *, provider_name: str | None, limit: int) -> list[ProviderHealthSnapshot]:
        query = select(ProviderHealthEventRecord)
        if provider_name is not None:
            query = query.where(ProviderHealthEventRecord.provider_name == provider_name)
        query = query.order_by(ProviderHealthEventRecord.observed_at.desc()).limit(max(limit, 0))
        return [self._deserialize(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize(self, payload_json: str) -> ProviderHealthSnapshot:
        payload = deserialize_payload(payload_json)
        for field in ("last_success_at", "last_failure_at", "observed_at"):
            payload[field] = ensure_aware_datetime(payload.get(field))
        return ProviderHealthSnapshot(**payload)

    def _upsert_ingest_run(self, session: Session, item: ProviderIngestRun) -> ProviderIngestRun:
        record = session.get(ProviderIngestRunRecord, item.run_id)
        payload = serialize_payload(item)
        if record is None:
            session.add(
                ProviderIngestRunRecord(
                    run_id=item.run_id,
                    provider_name=item.provider_name,
                    dataset_type=item.dataset_type,
                    status=item.status,
                    requested_at=item.requested_at,
                    completed_at=item.completed_at,
                    payload_json=payload,
                )
            )
        else:
            record.provider_name = item.provider_name
            record.dataset_type = item.dataset_type
            record.status = item.status
            record.requested_at = item.requested_at
            record.completed_at = item.completed_at
            record.payload_json = payload
        return item

    def _list_ingest_runs(self, session: Session, *, provider_name: str | None, limit: int) -> list[ProviderIngestRun]:
        query = select(ProviderIngestRunRecord)
        if provider_name is not None:
            query = query.where(ProviderIngestRunRecord.provider_name == provider_name)
        query = query.order_by(ProviderIngestRunRecord.requested_at.desc()).limit(max(limit, 0))
        items: list[ProviderIngestRun] = []
        for record in session.scalars(query).all():
            payload = deserialize_payload(record.payload_json)
            payload["requested_at"] = ensure_aware_datetime(payload.get("requested_at"))
            payload["completed_at"] = ensure_aware_datetime(payload.get("completed_at"))
            items.append(ProviderIngestRun(**payload))
        return items

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

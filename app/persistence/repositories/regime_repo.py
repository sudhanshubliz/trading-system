from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import RegimeSnapshotRecord
from app.regime.types import RegimeSnapshot


class RegimeRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_snapshot(self, snapshot: RegimeSnapshot, *, session: Session | None = None) -> RegimeSnapshot:
        return self._with_session(session, lambda db: self._upsert(db, snapshot))

    def get_latest_snapshot(self, symbol: str, *, session: Session | None = None) -> RegimeSnapshot | None:
        return self._with_session(session, lambda db: self._get_latest(db, symbol))

    def list_snapshots(
        self,
        *,
        symbol: str | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[RegimeSnapshot]:
        return self._with_session(session, lambda db: self._list(db, symbol=symbol, limit=limit)) or []

    def _upsert(self, session: Session, snapshot: RegimeSnapshot) -> RegimeSnapshot:
        now = utc_now()
        record = session.get(RegimeSnapshotRecord, snapshot.snapshot_id)
        payload = serialize_payload(snapshot)
        if record is None:
            record = RegimeSnapshotRecord(
                snapshot_id=snapshot.snapshot_id,
                symbol=snapshot.symbol,
                regime=snapshot.regime,
                confidence=snapshot.confidence,
                generated_at=snapshot.generated_at,
                payload_json=payload,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.symbol = snapshot.symbol
            record.regime = snapshot.regime
            record.confidence = snapshot.confidence
            record.generated_at = snapshot.generated_at
            record.payload_json = payload
            record.updated_at = now
        return snapshot

    def _get_latest(self, session: Session, symbol: str) -> RegimeSnapshot | None:
        query = (
            select(RegimeSnapshotRecord)
            .where(RegimeSnapshotRecord.symbol == symbol.upper())
            .order_by(RegimeSnapshotRecord.generated_at.desc())
            .limit(1)
        )
        record = session.scalar(query)
        if record is None:
            return None
        return self._deserialize(record.payload_json)

    def _list(self, session: Session, *, symbol: str | None, limit: int) -> list[RegimeSnapshot]:
        query = select(RegimeSnapshotRecord)
        if symbol is not None:
            query = query.where(RegimeSnapshotRecord.symbol == symbol.upper())
        query = query.order_by(RegimeSnapshotRecord.generated_at.desc()).limit(max(limit, 0))
        return [self._deserialize(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize(self, payload_json: str) -> RegimeSnapshot:
        payload = deserialize_payload(payload_json)
        payload["generated_at"] = ensure_aware_datetime(payload.get("generated_at"))
        return RegimeSnapshot(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

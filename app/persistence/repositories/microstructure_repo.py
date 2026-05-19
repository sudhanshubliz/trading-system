from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.features.microstructure.types import MicrostructureFeatureSnapshot
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import MicrostructureFeatureSnapshotRecord


class MicrostructureRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_snapshot(
        self,
        snapshot: MicrostructureFeatureSnapshot,
        *,
        session: Session | None = None,
    ) -> MicrostructureFeatureSnapshot:
        return self._with_session(session, lambda db: self._upsert(db, snapshot))

    def list_history(
        self,
        *,
        symbol: str | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[MicrostructureFeatureSnapshot]:
        return self._with_session(session, lambda db: self._list(db, symbol=symbol, limit=limit)) or []

    def get_latest(self, symbol: str, *, session: Session | None = None) -> MicrostructureFeatureSnapshot | None:
        return self._with_session(session, lambda db: self._get_latest(db, symbol))

    def _upsert(self, session: Session, snapshot: MicrostructureFeatureSnapshot) -> MicrostructureFeatureSnapshot:
        now = utc_now()
        record = session.get(MicrostructureFeatureSnapshotRecord, snapshot.snapshot_id)
        payload = serialize_payload(snapshot)
        if record is None:
            session.add(
                MicrostructureFeatureSnapshotRecord(
                    snapshot_id=snapshot.snapshot_id,
                    symbol=snapshot.symbol,
                    signal_policy=snapshot.signal_policy,
                    state=snapshot.market_state,
                    confidence=snapshot.confidence,
                    generated_at=snapshot.timestamp,
                    payload_json=payload,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            record.symbol = snapshot.symbol
            record.signal_policy = snapshot.signal_policy
            record.state = snapshot.market_state
            record.confidence = snapshot.confidence
            record.generated_at = snapshot.timestamp
            record.payload_json = payload
            record.updated_at = now
        return snapshot

    def _list(self, session: Session, *, symbol: str | None, limit: int) -> list[MicrostructureFeatureSnapshot]:
        query = select(MicrostructureFeatureSnapshotRecord)
        if symbol is not None:
            query = query.where(MicrostructureFeatureSnapshotRecord.symbol == symbol.upper())
        query = query.order_by(MicrostructureFeatureSnapshotRecord.generated_at.desc()).limit(max(limit, 0))
        return [self._deserialize(record.payload_json) for record in session.scalars(query).all()]

    def _get_latest(self, session: Session, symbol: str) -> MicrostructureFeatureSnapshot | None:
        query = (
            select(MicrostructureFeatureSnapshotRecord)
            .where(MicrostructureFeatureSnapshotRecord.symbol == symbol.upper())
            .order_by(MicrostructureFeatureSnapshotRecord.generated_at.desc())
            .limit(1)
        )
        record = session.scalar(query)
        if record is None:
            return None
        return self._deserialize(record.payload_json)

    def _deserialize(self, payload_json: str) -> MicrostructureFeatureSnapshot:
        payload = deserialize_payload(payload_json)
        payload["timestamp"] = ensure_aware_datetime(payload.get("timestamp"))
        return MicrostructureFeatureSnapshot(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

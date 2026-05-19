from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import PortfolioBrainSnapshotRecord, StrategyAllocationRecord
from app.portfolio_brain.types import AllocationRecommendation, PortfolioBrainSnapshot


class PortfolioBrainRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_snapshot(self, snapshot: PortfolioBrainSnapshot, *, session: Session | None = None) -> PortfolioBrainSnapshot:
        return self._with_session(session, lambda db: self._upsert_snapshot(db, snapshot))

    def append_allocation(self, item: AllocationRecommendation, *, session: Session | None = None) -> AllocationRecommendation:
        return self._with_session(session, lambda db: self._append_allocation(db, item))

    def list_snapshots(self, *, limit: int = 100, session: Session | None = None) -> list[PortfolioBrainSnapshot]:
        return self._with_session(session, lambda db: self._list_snapshots(db, limit=limit)) or []

    def list_allocations(self, *, limit: int = 100, session: Session | None = None) -> list[AllocationRecommendation]:
        return self._with_session(session, lambda db: self._list_allocations(db, limit=limit)) or []

    def _upsert_snapshot(self, session: Session, snapshot: PortfolioBrainSnapshot) -> PortfolioBrainSnapshot:
        record = session.get(PortfolioBrainSnapshotRecord, snapshot.snapshot_id)
        payload = serialize_payload(snapshot)
        if record is None:
            session.add(
                PortfolioBrainSnapshotRecord(
                    snapshot_id=snapshot.snapshot_id,
                    execution_mode=snapshot.execution_mode,
                    status="generated",
                    generated_at=snapshot.generated_at,
                    payload_json=payload,
                )
            )
        else:
            record.execution_mode = snapshot.execution_mode
            record.status = "generated"
            record.generated_at = snapshot.generated_at
            record.payload_json = payload
        return snapshot

    def _append_allocation(self, session: Session, item: AllocationRecommendation) -> AllocationRecommendation:
        session.add(
            StrategyAllocationRecord(
                allocation_id=item.allocation_id,
                strategy_name=item.strategy_name,
                scope_key=item.scope_key,
                status=item.status,
                capital_pct=item.capital_pct,
                generated_at=ensure_aware_datetime(item.metadata.get("generated_at")) or utc_now(),
                payload_json=serialize_payload(item),
            )
        )
        return item

    def _list_snapshots(self, session: Session, *, limit: int) -> list[PortfolioBrainSnapshot]:
        query = select(PortfolioBrainSnapshotRecord).order_by(PortfolioBrainSnapshotRecord.generated_at.desc()).limit(max(limit, 0))
        return [self._deserialize_snapshot(record.payload_json) for record in session.scalars(query).all()]

    def _list_allocations(self, session: Session, *, limit: int) -> list[AllocationRecommendation]:
        query = select(StrategyAllocationRecord).order_by(StrategyAllocationRecord.generated_at.desc()).limit(max(limit, 0))
        return [self._deserialize_allocation(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize_snapshot(self, payload_json: str) -> PortfolioBrainSnapshot:
        payload = deserialize_payload(payload_json)
        payload["generated_at"] = ensure_aware_datetime(payload.get("generated_at"))
        return PortfolioBrainSnapshot(**payload)

    def _deserialize_allocation(self, payload_json: str) -> AllocationRecommendation:
        return AllocationRecommendation(**deserialize_payload(payload_json))

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

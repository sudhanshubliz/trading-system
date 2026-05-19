from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.alpha_fusion.types import AlphaFeatureSnapshot, TimeframeFeatureVector
from app.features.tradingview_like.types import FeatureRun
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import FeatureRunRecord


class FeatureRunsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_run(self, run: FeatureRun, *, session: Session | None = None) -> FeatureRun:
        return self._with_session(session, lambda db: self._upsert(db, run))

    def get_run(self, run_id: str, *, session: Session | None = None) -> FeatureRun | None:
        return self._with_session(session, lambda db: self._get(db, run_id))

    def get_latest_run(self, symbol: str, *, session: Session | None = None) -> FeatureRun | None:
        return self._with_session(session, lambda db: self._get_latest(db, symbol))

    def list_runs(
        self,
        *,
        symbol: str | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[FeatureRun]:
        return self._with_session(session, lambda db: self._list(db, symbol=symbol, limit=limit)) or []

    def _upsert(self, session: Session, run: FeatureRun) -> FeatureRun:
        now = utc_now()
        record = session.get(FeatureRunRecord, run.run_id)
        payload = serialize_payload(run)
        if record is None:
            record = FeatureRunRecord(
                run_id=run.run_id,
                symbol=run.symbol,
                source_name=run.source_name,
                status=run.status,
                generated_at=run.generated_at,
                payload_json=payload,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.symbol = run.symbol
            record.source_name = run.source_name
            record.status = run.status
            record.generated_at = run.generated_at
            record.payload_json = payload
            record.updated_at = now
        return run

    def _get(self, session: Session, run_id: str) -> FeatureRun | None:
        record = session.get(FeatureRunRecord, run_id)
        if record is None:
            return None
        return self._deserialize(record.payload_json)

    def _get_latest(self, session: Session, symbol: str) -> FeatureRun | None:
        query = (
            select(FeatureRunRecord)
            .where(FeatureRunRecord.symbol == symbol.upper())
            .order_by(FeatureRunRecord.generated_at.desc())
            .limit(1)
        )
        record = session.scalar(query)
        if record is None:
            return None
        return self._deserialize(record.payload_json)

    def _list(self, session: Session, *, symbol: str | None, limit: int) -> list[FeatureRun]:
        query = select(FeatureRunRecord)
        if symbol is not None:
            query = query.where(FeatureRunRecord.symbol == symbol.upper())
        query = query.order_by(FeatureRunRecord.generated_at.desc()).limit(max(limit, 0))
        return [self._deserialize(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize(self, payload_json: str) -> FeatureRun:
        payload = deserialize_payload(payload_json)
        snapshot_payload = payload.get("feature_snapshot") or {}
        snapshot_payload["generated_at"] = ensure_aware_datetime(snapshot_payload.get("generated_at"))
        snapshot_payload["timeframes"] = {
            timeframe: TimeframeFeatureVector(**vector)
            for timeframe, vector in snapshot_payload.get("timeframes", {}).items()
        }
        payload["generated_at"] = ensure_aware_datetime(payload.get("generated_at"))
        payload["feature_snapshot"] = AlphaFeatureSnapshot(**snapshot_payload) if snapshot_payload else None
        return FeatureRun(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

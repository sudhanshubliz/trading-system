from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.alpha_fusion.types import AlphaFeatureSnapshot, AlphaSourceReading, FusedAlphaSignal, FusionComponent, TimeframeFeatureVector
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import FusedAlphaRecord


class AlphaFusionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_signal(self, signal: FusedAlphaSignal, *, session: Session | None = None) -> FusedAlphaSignal:
        return self._with_session(session, lambda db: self._upsert(db, signal))

    def get_signal(self, signal_id: str, *, session: Session | None = None) -> FusedAlphaSignal | None:
        return self._with_session(session, lambda db: self._get(db, signal_id))

    def list_signals(
        self,
        symbol: str | None = None,
        *,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[FusedAlphaSignal]:
        return self._with_session(session, lambda db: self._list(db, symbol=symbol, limit=limit)) or []

    def _upsert(self, session: Session, signal: FusedAlphaSignal) -> FusedAlphaSignal:
        now = utc_now()
        record = session.get(FusedAlphaRecord, signal.signal_id)
        payload = serialize_payload(asdict(signal))
        if record is None:
            record = FusedAlphaRecord(
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                direction=signal.direction,
                score=signal.score,
                confidence=signal.confidence,
                generated_at=signal.generated_at,
                payload_json=payload,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.symbol = signal.symbol
            record.direction = signal.direction
            record.score = signal.score
            record.confidence = signal.confidence
            record.generated_at = signal.generated_at
            record.payload_json = payload
            record.updated_at = now
        return signal

    def _get(self, session: Session, signal_id: str) -> FusedAlphaSignal | None:
        record = session.get(FusedAlphaRecord, signal_id)
        if record is None:
            return None
        return self._deserialize(record.payload_json)

    def _list(self, session: Session, *, symbol: str | None, limit: int) -> list[FusedAlphaSignal]:
        query = select(FusedAlphaRecord)
        if symbol is not None:
            query = query.where(FusedAlphaRecord.symbol == symbol.upper())
        query = query.order_by(FusedAlphaRecord.generated_at.desc()).limit(max(limit, 0))
        return [self._deserialize(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize(self, payload_json: str) -> FusedAlphaSignal:
        payload = deserialize_payload(payload_json)
        payload["generated_at"] = ensure_aware_datetime(payload.get("generated_at"))
        feature_snapshot = payload.get("feature_snapshot", {})
        feature_snapshot["generated_at"] = ensure_aware_datetime(feature_snapshot.get("generated_at"))
        feature_snapshot["timeframes"] = {
            timeframe: TimeframeFeatureVector(**vector)
            for timeframe, vector in feature_snapshot.get("timeframes", {}).items()
        }
        payload["feature_snapshot"] = AlphaFeatureSnapshot(**feature_snapshot)
        payload["components"] = [FusionComponent(**component) for component in payload.get("components", [])]
        payload.setdefault("confidence_band", "medium")
        payload.setdefault("strategy_family", "technical_features")
        payload.setdefault("supporting_factors", [])
        payload.setdefault("veto_factors", [])
        payload.setdefault("regime", None)
        payload.setdefault("metadata", {})
        payload["metadata"]["source_readings"] = [
            AlphaSourceReading(**{**reading, "timestamp": ensure_aware_datetime(reading.get("timestamp"))})
            for reading in payload["metadata"].get("source_readings", [])
        ]
        return FusedAlphaSignal(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

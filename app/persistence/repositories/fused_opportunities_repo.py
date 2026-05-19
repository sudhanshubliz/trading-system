from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.alpha_fusion.types import AlphaFeatureSnapshot, AlphaSourceReading, FusedAlphaSignal, FusionComponent, TimeframeFeatureVector
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import FusedOpportunityRecord


class FusedOpportunitiesRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_opportunity(
        self,
        signal: FusedAlphaSignal,
        *,
        session: Session | None = None,
    ) -> FusedAlphaSignal:
        return self._with_session(session, lambda db: self._upsert(db, signal))

    def get_opportunity(self, opportunity_id: str, *, session: Session | None = None) -> FusedAlphaSignal | None:
        return self._with_session(session, lambda db: self._get(db, opportunity_id))

    def list_opportunities(
        self,
        *,
        symbol_or_market: str | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[FusedAlphaSignal]:
        return self._with_session(
            session,
            lambda db: self._list(db, symbol_or_market=symbol_or_market, limit=limit),
        ) or []

    def _upsert(self, session: Session, signal: FusedAlphaSignal) -> FusedAlphaSignal:
        now = utc_now()
        record = session.get(FusedOpportunityRecord, signal.signal_id)
        payload = serialize_payload(signal)
        if record is None:
            record = FusedOpportunityRecord(
                opportunity_id=signal.signal_id,
                symbol_or_market=signal.symbol,
                direction=signal.direction,
                fused_score=signal.score,
                confidence=signal.confidence,
                strategy_family=signal.strategy_family,
                status=signal.status,
                generated_at=signal.generated_at,
                payload_json=payload,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.symbol_or_market = signal.symbol
            record.direction = signal.direction
            record.fused_score = signal.score
            record.confidence = signal.confidence
            record.strategy_family = signal.strategy_family
            record.status = signal.status
            record.generated_at = signal.generated_at
            record.payload_json = payload
            record.updated_at = now
        return signal

    def _get(self, session: Session, opportunity_id: str) -> FusedAlphaSignal | None:
        record = session.get(FusedOpportunityRecord, opportunity_id)
        if record is None:
            return None
        return self._deserialize(record.payload_json)

    def _list(self, session: Session, *, symbol_or_market: str | None, limit: int) -> list[FusedAlphaSignal]:
        query = select(FusedOpportunityRecord)
        if symbol_or_market is not None:
            query = query.where(FusedOpportunityRecord.symbol_or_market == symbol_or_market.upper())
        query = query.order_by(FusedOpportunityRecord.generated_at.desc()).limit(max(limit, 0))
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
        payload["metadata"] = dict(payload.get("metadata", {}))
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

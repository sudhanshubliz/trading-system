from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.alpha_fusion.types import AlphaSourceReading
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import AlphaSourceReadingRecord


class AlphaSourcesRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_reading(self, reading: AlphaSourceReading, *, session: Session | None = None) -> AlphaSourceReading:
        return self._with_session(session, lambda db: self._upsert(db, reading))

    def list_readings(
        self,
        *,
        symbol_or_market: str | None = None,
        source_name: str | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[AlphaSourceReading]:
        return self._with_session(
            session,
            lambda db: self._list(db, symbol_or_market=symbol_or_market, source_name=source_name, limit=limit),
        ) or []

    def _upsert(self, session: Session, reading: AlphaSourceReading) -> AlphaSourceReading:
        now = utc_now()
        record = session.get(AlphaSourceReadingRecord, reading.reading_id)
        payload = serialize_payload(reading)
        if record is None:
            record = AlphaSourceReadingRecord(
                reading_id=reading.reading_id,
                source_name=reading.source_name,
                symbol_or_market=reading.symbol_or_market,
                direction=reading.direction,
                confidence=reading.confidence,
                strategy_family=reading.strategy_family,
                timestamp=reading.timestamp,
                payload_json=payload,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.source_name = reading.source_name
            record.symbol_or_market = reading.symbol_or_market
            record.direction = reading.direction
            record.confidence = reading.confidence
            record.strategy_family = reading.strategy_family
            record.timestamp = reading.timestamp
            record.payload_json = payload
            record.updated_at = now
        return reading

    def _list(
        self,
        session: Session,
        *,
        symbol_or_market: str | None,
        source_name: str | None,
        limit: int,
    ) -> list[AlphaSourceReading]:
        query = select(AlphaSourceReadingRecord)
        if symbol_or_market is not None:
            query = query.where(AlphaSourceReadingRecord.symbol_or_market == symbol_or_market.upper())
        if source_name is not None:
            query = query.where(AlphaSourceReadingRecord.source_name == source_name)
        query = query.order_by(AlphaSourceReadingRecord.timestamp.desc()).limit(max(limit, 0))
        return [self._deserialize(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize(self, payload_json: str) -> AlphaSourceReading:
        payload = deserialize_payload(payload_json)
        payload["timestamp"] = ensure_aware_datetime(payload.get("timestamp"))
        return AlphaSourceReading(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

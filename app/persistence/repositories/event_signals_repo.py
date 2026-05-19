from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.event_signals.types import EventSignalCandidate, NormalizedEvent
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import EventObservationRecord, EventSignalRecord


class EventSignalsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_event(self, event: NormalizedEvent, *, session: Session | None = None) -> NormalizedEvent:
        return self._with_session(session, lambda db: self._upsert_event(db, event))

    def list_events(self, *, limit: int = 100, session: Session | None = None) -> list[NormalizedEvent]:
        return self._with_session(session, lambda db: self._list_events(db, limit=limit)) or []

    def get_event(self, event_id: str, *, session: Session | None = None) -> NormalizedEvent | None:
        return self._with_session(session, lambda db: self._get_event(db, event_id))

    def upsert_signal(self, signal: EventSignalCandidate, *, session: Session | None = None) -> EventSignalCandidate:
        return self._with_session(session, lambda db: self._upsert_signal(db, signal))

    def list_signals(self, *, limit: int = 100, session: Session | None = None) -> list[EventSignalCandidate]:
        return self._with_session(session, lambda db: self._list_signals(db, limit=limit)) or []

    def _upsert_event(self, session: Session, event: NormalizedEvent) -> NormalizedEvent:
        record = session.get(EventObservationRecord, event.event_id)
        payload = serialize_payload(event)
        if record is None:
            session.add(
                EventObservationRecord(
                    observation_id=event.event_id,
                    provider_name=event.source,
                    external_event_id=event.event_id,
                    observed_at=event.detection_time,
                    payload_json=payload,
                )
            )
        else:
            record.provider_name = event.source
            record.external_event_id = event.event_id
            record.observed_at = event.detection_time
            record.payload_json = payload
        return event

    def _list_events(self, session: Session, *, limit: int) -> list[NormalizedEvent]:
        query = select(EventObservationRecord).order_by(EventObservationRecord.observed_at.desc()).limit(max(limit, 0))
        return [self._deserialize_event(record.payload_json) for record in session.scalars(query).all()]

    def _get_event(self, session: Session, event_id: str) -> NormalizedEvent | None:
        record = session.get(EventObservationRecord, event_id)
        return self._deserialize_event(record.payload_json) if record is not None else None

    def _upsert_signal(self, session: Session, signal: EventSignalCandidate) -> EventSignalCandidate:
        record = session.get(EventSignalRecord, signal.signal_id)
        payload = serialize_payload(signal)
        if record is None:
            session.add(
                EventSignalRecord(
                    signal_id=signal.signal_id,
                    event_id=signal.event_id,
                    symbol_or_market=signal.symbol_or_market,
                    direction=signal.direction,
                    confidence=signal.confidence,
                    generated_at=signal.timestamp,
                    payload_json=payload,
                )
            )
        else:
            record.event_id = signal.event_id
            record.symbol_or_market = signal.symbol_or_market
            record.direction = signal.direction
            record.confidence = signal.confidence
            record.generated_at = signal.timestamp
            record.payload_json = payload
        return signal

    def _list_signals(self, session: Session, *, limit: int) -> list[EventSignalCandidate]:
        query = select(EventSignalRecord).order_by(EventSignalRecord.generated_at.desc()).limit(max(limit, 0))
        return [self._deserialize_signal(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize_event(self, payload_json: str) -> NormalizedEvent:
        payload = deserialize_payload(payload_json)
        payload["event_time"] = ensure_aware_datetime(payload.get("event_time"))
        payload["detection_time"] = ensure_aware_datetime(payload.get("detection_time"))
        return NormalizedEvent(**payload)

    def _deserialize_signal(self, payload_json: str) -> EventSignalCandidate:
        payload = deserialize_payload(payload_json)
        payload["timestamp"] = ensure_aware_datetime(payload.get("timestamp"))
        return EventSignalCandidate(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)


from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import SignalRecord
from app.signals.types import CandidateSignal


class SignalsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_signal(self, signal: CandidateSignal, *, session: Session | None = None) -> CandidateSignal:
        return self._with_session(session, lambda db: self._upsert(db, signal))

    def get_signal(self, signal_id: str, *, session: Session | None = None) -> CandidateSignal | None:
        return self._with_session(session, lambda db: self._get(db, signal_id))

    def _upsert(self, session: Session, signal: CandidateSignal) -> CandidateSignal:
        now = utc_now()
        record = session.get(SignalRecord, signal.signal_id)
        if record is None:
            record = SignalRecord(
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                strategy_name=signal.strategy_name,
                status=signal.status,
                generated_at=signal.generated_at,
                payload_json=serialize_payload(asdict(signal)),
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.symbol = signal.symbol
            record.strategy_name = signal.strategy_name
            record.status = signal.status
            record.generated_at = signal.generated_at
            record.payload_json = serialize_payload(asdict(signal))
            record.updated_at = now
        return signal

    def _get(self, session: Session, signal_id: str) -> CandidateSignal | None:
        record = session.get(SignalRecord, signal_id)
        if record is None:
            return None
        payload = deserialize_payload(record.payload_json)
        payload["generated_at"] = ensure_aware_datetime(payload.get("generated_at"))
        return CandidateSignal(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], CandidateSignal | None]) -> CandidateSignal | None:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

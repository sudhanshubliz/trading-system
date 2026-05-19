from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import WalletObservationRecord, WalletProfileRecord, WalletSignalRecord
from app.wallet_intel.types import WalletObservation, WalletProfile, WalletSignal


class WalletRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_profile(self, profile: WalletProfile, *, session: Session | None = None) -> WalletProfile:
        return self._with_session(session, lambda db: self._upsert_profile(db, profile))

    def list_profiles(self, *, session: Session | None = None) -> list[WalletProfile]:
        return self._with_session(session, self._list_profiles) or []

    def get_profile(self, wallet_id: str, *, session: Session | None = None) -> WalletProfile | None:
        return self._with_session(session, lambda db: self._get_profile(db, wallet_id))

    def append_observation(self, observation: WalletObservation, *, session: Session | None = None) -> WalletObservation:
        return self._with_session(session, lambda db: self._append_observation(db, observation))

    def list_observations(self, *, wallet_id: str | None = None, limit: int = 100, session: Session | None = None) -> list[WalletObservation]:
        return self._with_session(session, lambda db: self._list_observations(db, wallet_id=wallet_id, limit=limit)) or []

    def upsert_signal(self, signal: WalletSignal, *, session: Session | None = None) -> WalletSignal:
        return self._with_session(session, lambda db: self._upsert_signal(db, signal))

    def list_signals(self, *, wallet_id: str | None = None, limit: int = 100, session: Session | None = None) -> list[WalletSignal]:
        return self._with_session(session, lambda db: self._list_signals(db, wallet_id=wallet_id, limit=limit)) or []

    def _upsert_profile(self, session: Session, profile: WalletProfile) -> WalletProfile:
        record = session.get(WalletProfileRecord, profile.wallet_id)
        payload = serialize_payload(profile)
        if record is None:
            session.add(
                WalletProfileRecord(
                    wallet_id=profile.wallet_id,
                    provider_name=profile.provider,
                    score=profile.quality_score,
                    updated_at=profile.last_seen,
                    payload_json=payload,
                )
            )
        else:
            record.provider_name = profile.provider
            record.score = profile.quality_score
            record.updated_at = profile.last_seen
            record.payload_json = payload
        return profile

    def _list_profiles(self, session: Session) -> list[WalletProfile]:
        query = select(WalletProfileRecord).order_by(WalletProfileRecord.score.desc())
        return [self._deserialize_profile(record.payload_json) for record in session.scalars(query).all()]

    def _get_profile(self, session: Session, wallet_id: str) -> WalletProfile | None:
        record = session.get(WalletProfileRecord, wallet_id)
        return self._deserialize_profile(record.payload_json) if record is not None else None

    def _append_observation(self, session: Session, observation: WalletObservation) -> WalletObservation:
        session.add(
            WalletObservationRecord(
                observation_id=observation.observation_id,
                wallet_id=observation.wallet_id,
                observed_at=observation.observed_at,
                payload_json=serialize_payload(observation),
                created_at=observation.observed_at,
            )
        )
        return observation

    def _list_observations(self, session: Session, *, wallet_id: str | None, limit: int) -> list[WalletObservation]:
        query = select(WalletObservationRecord)
        if wallet_id is not None:
            query = query.where(WalletObservationRecord.wallet_id == wallet_id)
        query = query.order_by(WalletObservationRecord.observed_at.desc()).limit(max(limit, 0))
        return [self._deserialize_observation(record.payload_json) for record in session.scalars(query).all()]

    def _upsert_signal(self, session: Session, signal: WalletSignal) -> WalletSignal:
        record = session.get(WalletSignalRecord, signal.signal_id)
        payload = serialize_payload(signal)
        if record is None:
            session.add(
                WalletSignalRecord(
                    signal_id=signal.signal_id,
                    wallet_id=signal.wallet_id,
                    symbol_or_market=signal.symbol_or_market,
                    direction=signal.direction,
                    confidence=signal.confidence,
                    generated_at=signal.timestamp,
                    payload_json=payload,
                )
            )
        else:
            record.wallet_id = signal.wallet_id
            record.symbol_or_market = signal.symbol_or_market
            record.direction = signal.direction
            record.confidence = signal.confidence
            record.generated_at = signal.timestamp
            record.payload_json = payload
        return signal

    def _list_signals(self, session: Session, *, wallet_id: str | None, limit: int) -> list[WalletSignal]:
        query = select(WalletSignalRecord)
        if wallet_id is not None:
            query = query.where(WalletSignalRecord.wallet_id == wallet_id)
        query = query.order_by(WalletSignalRecord.generated_at.desc()).limit(max(limit, 0))
        return [self._deserialize_signal(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize_profile(self, payload_json: str) -> WalletProfile:
        payload = deserialize_payload(payload_json)
        payload["first_seen"] = ensure_aware_datetime(payload.get("first_seen"))
        payload["last_seen"] = ensure_aware_datetime(payload.get("last_seen"))
        return WalletProfile(**payload)

    def _deserialize_observation(self, payload_json: str) -> WalletObservation:
        payload = deserialize_payload(payload_json)
        payload["observed_at"] = ensure_aware_datetime(payload.get("observed_at"))
        return WalletObservation(**payload)

    def _deserialize_signal(self, payload_json: str) -> WalletSignal:
        payload = deserialize_payload(payload_json)
        payload["timestamp"] = ensure_aware_datetime(payload.get("timestamp"))
        return WalletSignal(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)


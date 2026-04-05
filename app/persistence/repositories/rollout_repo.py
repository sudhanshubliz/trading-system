from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.live.types import LiveRolloutState, RolloutHistoryEntry
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import EventRecord, RolloutStateRecord

ROLLOUT_STATE_KEY = "live_rollout"


class RolloutRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def get_rollout_state(self, *, session: Session | None = None) -> LiveRolloutState | None:
        return self._with_session(session, self._get_rollout_state)

    def upsert_rollout_state(
        self,
        state: LiveRolloutState,
        *,
        session: Session | None = None,
    ) -> LiveRolloutState:
        return self._with_session(session, lambda db: self._upsert_rollout_state(db, state))

    def append_phase_change_event(
        self,
        *,
        event_type: str,
        phase: str,
        capital_limit: float,
        changed_by: str | None = None,
        reason: str | None = None,
        rollback_active: bool = False,
        payload: dict[str, Any] | None = None,
        session: Session | None = None,
    ) -> RolloutHistoryEntry:
        return self._with_session(
            session,
            lambda db: self._append_phase_change_event(
                db,
                event_type=event_type,
                phase=phase,
                capital_limit=capital_limit,
                changed_by=changed_by,
                reason=reason,
                rollback_active=rollback_active,
                payload=payload or {},
            ),
        )

    def list_phase_history(
        self,
        *,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[RolloutHistoryEntry]:
        return self._with_session(session, lambda db: self._list_phase_history(db, limit=limit)) or []

    def _get_rollout_state(self, session: Session) -> LiveRolloutState | None:
        record = session.get(RolloutStateRecord, ROLLOUT_STATE_KEY)
        if record is None:
            return None
        payload = deserialize_payload(record.payload_json)
        payload["last_phase_change_at"] = ensure_aware_datetime(payload.get("last_phase_change_at"))
        payload["updated_at"] = ensure_aware_datetime(payload.get("updated_at"))
        return LiveRolloutState(**payload)

    def _upsert_rollout_state(self, session: Session, state: LiveRolloutState) -> LiveRolloutState:
        payload = asdict(state)
        now = utc_now()
        record = session.get(RolloutStateRecord, ROLLOUT_STATE_KEY)
        if record is None:
            record = RolloutStateRecord(
                state_key=ROLLOUT_STATE_KEY,
                current_phase=state.current_phase,
                current_capital_limit=f"{state.current_capital_limit:.8f}",
                rollback_active="true" if state.rollback_active else "false",
                updated_at=state.updated_at or now,
                payload_json=serialize_payload(payload),
            )
            session.add(record)
        else:
            record.current_phase = state.current_phase
            record.current_capital_limit = f"{state.current_capital_limit:.8f}"
            record.rollback_active = "true" if state.rollback_active else "false"
            record.updated_at = state.updated_at or now
            record.payload_json = serialize_payload(payload)
        return state

    def _append_phase_change_event(
        self,
        session: Session,
        *,
        event_type: str,
        phase: str,
        capital_limit: float,
        changed_by: str | None,
        reason: str | None,
        rollback_active: bool,
        payload: dict[str, Any],
    ) -> RolloutHistoryEntry:
        timestamp = utc_now()
        event_payload = {
            "event_type": event_type,
            "entity_id": ROLLOUT_STATE_KEY,
            "phase": phase,
            "capital_limit": capital_limit,
            "changed_by": changed_by,
            "reason": reason,
            "rollback_active": rollback_active,
            "timestamp": timestamp,
            **payload,
        }
        session.add(
            EventRecord(
                event_type=event_type,
                entity_id=ROLLOUT_STATE_KEY,
                execution_mode="live",
                timestamp=timestamp,
                payload_json=serialize_payload(event_payload),
            )
        )
        return RolloutHistoryEntry(
            event_type=event_type,
            phase=phase,
            capital_limit=capital_limit,
            changed_by=changed_by,
            reason=reason,
            rollback_active=rollback_active,
            timestamp=timestamp,
        )

    def _list_phase_history(self, session: Session, *, limit: int) -> list[RolloutHistoryEntry]:
        event_types = (
            "rollout_phase_changed",
            "rollout_scale_up",
            "rollout_scale_down",
            "rollout_auto_rollback",
            "rollout_manual_rollback",
        )
        query = (
            select(EventRecord)
            .where(EventRecord.entity_id == ROLLOUT_STATE_KEY)
            .where(EventRecord.event_type.in_(event_types))
            .order_by(EventRecord.timestamp.desc())
            .limit(max(limit, 0))
        )
        items: list[RolloutHistoryEntry] = []
        for record in session.scalars(query).all():
            payload = deserialize_payload(record.payload_json)
            items.append(
                RolloutHistoryEntry(
                    event_type=record.event_type,
                    phase=str(payload.get("phase", "disabled")),
                    capital_limit=float(payload.get("capital_limit", 0.0) or 0.0),
                    changed_by=payload.get("changed_by"),
                    reason=payload.get("reason"),
                    rollback_active=bool(payload.get("rollback_active", False)),
                    timestamp=ensure_aware_datetime(record.timestamp),
                )
            )
        return items

    def _with_session(self, session: Session | None, callback: Callable[[Session], Any]) -> Any:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

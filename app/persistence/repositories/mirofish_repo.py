from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import MiroFishSimulationRunRecord
from app.simulation.types import MiroFishScenarioSummary


class MiroFishRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_run(self, summary: MiroFishScenarioSummary, *, session: Session | None = None) -> MiroFishScenarioSummary:
        return self._with_session(session, lambda db: self._upsert(db, summary))

    def get_latest(self, *, session: Session | None = None) -> MiroFishScenarioSummary | None:
        return self._with_session(session, self._get_latest)

    def _upsert(self, session: Session, summary: MiroFishScenarioSummary) -> MiroFishScenarioSummary:
        record = session.get(MiroFishSimulationRunRecord, summary.run_id)
        payload = serialize_payload(summary)
        if record is None:
            session.add(
                MiroFishSimulationRunRecord(
                    run_id=summary.run_id,
                    status="completed",
                    symbol_or_market=summary.symbol_or_market,
                    generated_at=summary.timestamp,
                    payload_json=payload,
                )
            )
        else:
            record.status = "completed"
            record.symbol_or_market = summary.symbol_or_market
            record.generated_at = summary.timestamp
            record.payload_json = payload
        return summary

    def _get_latest(self, session: Session) -> MiroFishScenarioSummary | None:
        query = select(MiroFishSimulationRunRecord).order_by(MiroFishSimulationRunRecord.generated_at.desc()).limit(1)
        record = session.scalar(query)
        if record is None:
            return None
        payload = deserialize_payload(record.payload_json)
        payload["timestamp"] = ensure_aware_datetime(payload.get("timestamp"))
        return MiroFishScenarioSummary(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import RiskAssessmentRecord
from app.risk.types import RiskAssessment, RiskCheckResult


class RiskRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_assessment(self, assessment: RiskAssessment, *, session: Session | None = None) -> RiskAssessment:
        return self._with_session(session, lambda db: self._upsert(db, assessment))

    def get_assessment(self, assessment_id: str, *, session: Session | None = None) -> RiskAssessment | None:
        return self._with_session(session, lambda db: self._get(db, assessment_id))

    def _upsert(self, session: Session, assessment: RiskAssessment) -> RiskAssessment:
        now = utc_now()
        record = session.get(RiskAssessmentRecord, assessment.assessment_id)
        payload = asdict(assessment)
        if record is None:
            record = RiskAssessmentRecord(
                assessment_id=assessment.assessment_id,
                signal_id=assessment.signal_id,
                symbol=assessment.symbol,
                final_decision=assessment.final_decision,
                assessed_at=assessment.assessed_at,
                payload_json=serialize_payload(payload),
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.signal_id = assessment.signal_id
            record.symbol = assessment.symbol
            record.final_decision = assessment.final_decision
            record.assessed_at = assessment.assessed_at
            record.payload_json = serialize_payload(payload)
            record.updated_at = now
        return assessment

    def _get(self, session: Session, assessment_id: str) -> RiskAssessment | None:
        record = session.get(RiskAssessmentRecord, assessment_id)
        if record is None:
            return None
        payload = deserialize_payload(record.payload_json)
        payload["assessed_at"] = ensure_aware_datetime(payload.get("assessed_at"))
        payload["checks"] = [RiskCheckResult(**item) for item in payload.get("checks", [])]
        return RiskAssessment(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], RiskAssessment | None]) -> RiskAssessment | None:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

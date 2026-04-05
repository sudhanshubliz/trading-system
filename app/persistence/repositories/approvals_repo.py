from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.execution.types import Approval
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import ApprovalRecord


class ApprovalsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_approval(self, approval: Approval, *, session: Session | None = None) -> Approval:
        return self._with_session(session, lambda db: self._upsert(db, approval))

    def get_approval(self, approval_id: str, *, session: Session | None = None) -> Approval | None:
        return self._with_session(session, lambda db: self._get(db, approval_id))

    def find_by_assessment_id(self, assessment_id: str, *, session: Session | None = None) -> Approval | None:
        return self._with_session(session, lambda db: self._get_by_assessment(db, assessment_id))

    def list_pending(self, execution_mode: str, *, session: Session | None = None) -> list[Approval]:
        return self._with_session(session, lambda db: self._list_by_status(db, execution_mode, "pending")) or []

    def list_approvals(self, execution_mode: str, *, session: Session | None = None) -> list[Approval]:
        return self._with_session(session, lambda db: self._list_all(db, execution_mode)) or []

    def _upsert(self, session: Session, approval: Approval) -> Approval:
        now = utc_now()
        record = session.get(ApprovalRecord, approval.approval_id)
        payload = asdict(approval)
        if record is None:
            record = ApprovalRecord(
                approval_id=approval.approval_id,
                assessment_id=approval.assessment_id,
                signal_id=approval.signal_id,
                symbol=approval.symbol,
                status=approval.status,
                execution_mode=approval.execution_mode,
                created_at=approval.created_at,
                updated_at=now,
                payload_json=serialize_payload(payload),
            )
            session.add(record)
        else:
            record.assessment_id = approval.assessment_id
            record.signal_id = approval.signal_id
            record.symbol = approval.symbol
            record.status = approval.status
            record.execution_mode = approval.execution_mode
            record.updated_at = now
            record.payload_json = serialize_payload(payload)
        return approval

    def _get(self, session: Session, approval_id: str) -> Approval | None:
        record = session.get(ApprovalRecord, approval_id)
        if record is None:
            return None
        return self._to_approval(record)

    def _get_by_assessment(self, session: Session, assessment_id: str) -> Approval | None:
        query = select(ApprovalRecord).where(ApprovalRecord.assessment_id == assessment_id).order_by(ApprovalRecord.updated_at.desc())
        record = session.scalars(query).first()
        if record is None:
            return None
        return self._to_approval(record)

    def _list_all(self, session: Session, execution_mode: str) -> list[Approval]:
        query = (
            select(ApprovalRecord)
            .where(ApprovalRecord.execution_mode == execution_mode)
            .order_by(ApprovalRecord.created_at.desc())
        )
        return [self._to_approval(record) for record in session.scalars(query).all()]

    def _list_by_status(self, session: Session, execution_mode: str, status: str) -> list[Approval]:
        query = (
            select(ApprovalRecord)
            .where(ApprovalRecord.execution_mode == execution_mode, ApprovalRecord.status == status)
            .order_by(ApprovalRecord.created_at.desc())
        )
        return [self._to_approval(record) for record in session.scalars(query).all()]

    def _to_approval(self, record: ApprovalRecord) -> Approval:
        payload = deserialize_payload(record.payload_json)
        for field in ("created_at", "approved_at", "rejected_at", "executed_at"):
            payload[field] = ensure_aware_datetime(payload.get(field))
        payload.setdefault("execution_mode", record.execution_mode)
        return Approval(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], Approval | list[Approval] | None]) -> Approval | list[Approval] | None:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.execution.types import Position
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import PositionRecord


class PositionsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_position(self, position: Position, *, session: Session | None = None) -> Position:
        return self._with_session(session, lambda db: self._upsert(db, position))

    def list_positions(self, execution_mode: str | None = None, *, session: Session | None = None) -> list[Position]:
        return self._with_session(session, lambda db: self._list(db, execution_mode)) or []

    def list_open_positions(self, execution_mode: str | None = None, *, session: Session | None = None) -> list[Position]:
        return self._with_session(session, lambda db: self._list_open(db, execution_mode)) or []

    def get_position(self, position_id: str, *, session: Session | None = None) -> Position | None:
        return self._with_session(session, lambda db: self._get(db, position_id))

    def _upsert(self, session: Session, position: Position) -> Position:
        record = session.get(PositionRecord, position.position_id)
        payload = asdict(position)
        if record is None:
            record = PositionRecord(
                position_id=position.position_id,
                trade_id=position.trade_id,
                approval_id=position.approval_id,
                signal_id=position.signal_id,
                symbol=position.symbol,
                status=position.status,
                execution_mode=position.execution_mode,
                reconciliation_status=position.reconciliation_status,
                last_reconciled_at=position.last_reconciled_at,
                opened_at=position.opened_at,
                updated_at=position.updated_at,
                closed_at=position.closed_at,
                payload_json=serialize_payload(payload),
            )
            session.add(record)
        else:
            record.trade_id = position.trade_id
            record.approval_id = position.approval_id
            record.signal_id = position.signal_id
            record.symbol = position.symbol
            record.status = position.status
            record.execution_mode = position.execution_mode
            record.reconciliation_status = position.reconciliation_status
            record.last_reconciled_at = position.last_reconciled_at
            record.opened_at = position.opened_at
            record.updated_at = position.updated_at
            record.closed_at = position.closed_at
            record.payload_json = serialize_payload(payload)
        return position

    def _list(self, session: Session, execution_mode: str | None) -> list[Position]:
        query = select(PositionRecord)
        if execution_mode is not None:
            query = query.where(PositionRecord.execution_mode == execution_mode)
        query = query.order_by(PositionRecord.opened_at.desc())
        return [self._to_position(record) for record in session.scalars(query).all()]

    def _list_open(self, session: Session, execution_mode: str | None) -> list[Position]:
        query = select(PositionRecord).where(PositionRecord.status != "closed")
        if execution_mode is not None:
            query = query.where(PositionRecord.execution_mode == execution_mode)
        query = query.order_by(PositionRecord.opened_at.desc())
        return [self._to_position(record) for record in session.scalars(query).all()]

    def _get(self, session: Session, position_id: str) -> Position | None:
        record = session.get(PositionRecord, position_id)
        if record is None:
            return None
        return self._to_position(record)

    def _to_position(self, record: PositionRecord) -> Position:
        payload = deserialize_payload(record.payload_json)
        for field in ("opened_at", "updated_at", "closed_at", "last_reconciled_at"):
            payload[field] = ensure_aware_datetime(payload.get(field))
        return Position(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], Position | list[Position] | None]) -> Position | list[Position] | None:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.execution.types import Trade
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import TradeRecord


class TradesRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_trade(self, trade: Trade, *, session: Session | None = None) -> Trade:
        return self._with_session(session, lambda db: self._upsert(db, trade))

    def list_trades(self, execution_mode: str | None = None, *, session: Session | None = None) -> list[Trade]:
        return self._with_session(session, lambda db: self._list(db, execution_mode)) or []

    def get_trade(self, trade_id: str, *, session: Session | None = None) -> Trade | None:
        return self._with_session(session, lambda db: self._get(db, trade_id))

    def get_trade_by_client_order_id(self, client_order_id: str, *, session: Session | None = None) -> Trade | None:
        return self._with_session(session, lambda db: self._get_by_client_order_id(db, client_order_id))

    def _upsert(self, session: Session, trade: Trade) -> Trade:
        now = utc_now()
        record = session.get(TradeRecord, trade.trade_id)
        payload = asdict(trade)
        if record is None:
            record = TradeRecord(
                trade_id=trade.trade_id,
                approval_id=trade.approval_id,
                position_id=trade.position_id,
                signal_id=trade.signal_id,
                symbol=trade.symbol,
                status=trade.status,
                execution_mode=trade.execution_mode,
                client_order_id=trade.client_order_id,
                exchange_order_id=trade.exchange_order_id,
                exchange_status=trade.exchange_status,
                reconciliation_status=trade.reconciliation_status,
                last_reconciled_at=trade.last_reconciled_at,
                opened_at=trade.opened_at,
                updated_at=trade.updated_at,
                closed_at=trade.closed_at,
                payload_json=serialize_payload(payload),
            )
            session.add(record)
        else:
            record.approval_id = trade.approval_id
            record.position_id = trade.position_id
            record.signal_id = trade.signal_id
            record.symbol = trade.symbol
            record.status = trade.status
            record.execution_mode = trade.execution_mode
            record.client_order_id = trade.client_order_id
            record.exchange_order_id = trade.exchange_order_id
            record.exchange_status = trade.exchange_status
            record.reconciliation_status = trade.reconciliation_status
            record.last_reconciled_at = trade.last_reconciled_at
            record.opened_at = trade.opened_at
            record.updated_at = trade.updated_at or now
            record.closed_at = trade.closed_at
            record.payload_json = serialize_payload(payload)
        return trade

    def _list(self, session: Session, execution_mode: str | None) -> list[Trade]:
        query = select(TradeRecord)
        if execution_mode is not None:
            query = query.where(TradeRecord.execution_mode == execution_mode)
        query = query.order_by(TradeRecord.opened_at.desc())
        return [self._to_trade(record) for record in session.scalars(query).all()]

    def _get(self, session: Session, trade_id: str) -> Trade | None:
        record = session.get(TradeRecord, trade_id)
        if record is None:
            return None
        return self._to_trade(record)

    def _get_by_client_order_id(self, session: Session, client_order_id: str) -> Trade | None:
        query = select(TradeRecord).where(TradeRecord.client_order_id == client_order_id)
        record = session.scalars(query).first()
        if record is None:
            return None
        return self._to_trade(record)

    def _to_trade(self, record: TradeRecord) -> Trade:
        payload = deserialize_payload(record.payload_json)
        for field in ("opened_at", "updated_at", "closed_at", "last_reconciled_at"):
            payload[field] = ensure_aware_datetime(payload.get(field))
        return Trade(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], Trade | list[Trade] | None]) -> Trade | list[Trade] | None:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

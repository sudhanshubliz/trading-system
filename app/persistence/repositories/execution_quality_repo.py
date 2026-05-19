from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.execution_quality.types import ExecutionQualityRecordData
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import ExecutionQualityRecord


class ExecutionQualityRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_record(
        self,
        record_data: ExecutionQualityRecordData,
        *,
        session: Session | None = None,
    ) -> ExecutionQualityRecordData:
        return self._with_session(session, lambda db: self._upsert(db, record_data))

    def get_by_trade_id(self, trade_id: str, *, session: Session | None = None) -> list[ExecutionQualityRecordData]:
        return self._with_session(session, lambda db: self._get_by_trade_id(db, trade_id)) or []

    def list_records(
        self,
        *,
        mode: str | None = None,
        symbol: str | None = None,
        strategy_name: str | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[ExecutionQualityRecordData]:
        return self._with_session(
            session,
            lambda db: self._list(
                db,
                mode=mode,
                symbol=symbol,
                strategy_name=strategy_name,
                min_score=min_score,
                max_score=max_score,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            ),
        ) or []

    def _upsert(self, session: Session, record_data: ExecutionQualityRecordData) -> ExecutionQualityRecordData:
        record = session.get(ExecutionQualityRecord, record_data.record_id)
        payload = serialize_payload(record_data)
        if record is None:
            session.add(
                ExecutionQualityRecord(
                    record_id=record_data.record_id,
                    trade_id=record_data.trade_id,
                    symbol=record_data.symbol,
                    execution_mode=record_data.mode,
                    quality_score=record_data.fill_quality_score,
                    recorded_at=record_data.recorded_at,
                    payload_json=payload,
                )
            )
        else:
            record.trade_id = record_data.trade_id
            record.symbol = record_data.symbol
            record.execution_mode = record_data.mode
            record.quality_score = record_data.fill_quality_score
            record.recorded_at = record_data.recorded_at
            record.payload_json = payload
        return record_data

    def _get_by_trade_id(self, session: Session, trade_id: str) -> list[ExecutionQualityRecordData]:
        query = select(ExecutionQualityRecord).where(ExecutionQualityRecord.trade_id == trade_id)
        return [self._deserialize(item.payload_json) for item in session.scalars(query).all()]

    def _list(
        self,
        session: Session,
        *,
        mode: str | None,
        symbol: str | None,
        strategy_name: str | None,
        min_score: float | None,
        max_score: float | None,
        start_time: datetime | None,
        end_time: datetime | None,
        limit: int,
    ) -> list[ExecutionQualityRecordData]:
        query = select(ExecutionQualityRecord)
        if mode is not None:
            query = query.where(ExecutionQualityRecord.execution_mode == mode)
        if symbol is not None:
            query = query.where(ExecutionQualityRecord.symbol == symbol.upper())
        if min_score is not None:
            query = query.where(ExecutionQualityRecord.quality_score >= min_score)
        if max_score is not None:
            query = query.where(ExecutionQualityRecord.quality_score <= max_score)
        if start_time is not None:
            query = query.where(ExecutionQualityRecord.recorded_at >= start_time)
        if end_time is not None:
            query = query.where(ExecutionQualityRecord.recorded_at <= end_time)
        query = query.order_by(ExecutionQualityRecord.recorded_at.desc()).limit(max(limit, 0))
        items = [self._deserialize(record.payload_json) for record in session.scalars(query).all()]
        if strategy_name is not None:
            items = [item for item in items if item.strategy_name == strategy_name]
        return items

    def _deserialize(self, payload_json: str) -> ExecutionQualityRecordData:
        payload = deserialize_payload(payload_json)
        for field in ("decision_timestamp", "submit_timestamp", "fill_timestamp", "recorded_at"):
            payload[field] = ensure_aware_datetime(payload.get(field))
        payload.setdefault("decision_to_order_latency_ms", payload.get("latency_ms"))
        payload.setdefault("order_to_fill_latency_ms", None)
        payload.setdefault("total_latency_ms", payload.get("latency_ms"))
        payload.setdefault("expected_price", payload.get("intended_price"))
        payload.setdefault("simulated_fill_price", payload.get("actual_fill_price"))
        payload.setdefault("slippage_bps", payload.get("realized_slippage_bps"))
        payload.setdefault("liquidity_used_pct", None)
        payload.setdefault("stale_data_flag", False)
        payload.setdefault("provider_health_at_execution", None)
        return ExecutionQualityRecordData(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import ReplayFidelityMetadataRecord, ReplayRunRecord
from app.replay.types import EquityPoint, ReplayFidelityMetadata, ReplayMetrics, ReplayRun, ReplayTradeResult


class ReplayRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_replay_run(self, run: ReplayRun, *, session: Session | None = None) -> ReplayRun:
        return self._with_session(session, lambda db: self._upsert(db, run))

    def get_replay_run(self, run_id: str, *, session: Session | None = None) -> ReplayRun | None:
        return self._with_session(session, lambda db: self._get(db, run_id))

    def list_runs(self, *, session: Session | None = None) -> list[ReplayRun]:
        return self._with_session(session, self._list) or []

    def _upsert(self, session: Session, run: ReplayRun) -> ReplayRun:
        now = utc_now()
        record = session.get(ReplayRunRecord, run.run_id)
        payload = asdict(run)
        if record is None:
            record = ReplayRunRecord(
                run_id=run.run_id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                payload_json=serialize_payload(payload),
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.status = run.status
            record.started_at = run.started_at
            record.completed_at = run.completed_at
            record.payload_json = serialize_payload(payload)
            record.updated_at = now
        if run.fidelity_metadata is not None:
            fidelity_record = session.get(ReplayFidelityMetadataRecord, run.run_id)
            fidelity_payload = asdict(run.fidelity_metadata)
            generated_at = run.fidelity_metadata.generated_at or run.completed_at or now
            if fidelity_record is None:
                session.add(
                    ReplayFidelityMetadataRecord(
                        run_id=run.run_id,
                        fidelity_mode=run.fidelity_metadata.fidelity_mode,
                        generated_at=generated_at,
                        payload_json=serialize_payload(fidelity_payload),
                    )
                )
            else:
                fidelity_record.fidelity_mode = run.fidelity_metadata.fidelity_mode
                fidelity_record.generated_at = generated_at
                fidelity_record.payload_json = serialize_payload(fidelity_payload)
        return run

    def _get(self, session: Session, run_id: str) -> ReplayRun | None:
        record = session.get(ReplayRunRecord, run_id)
        if record is None:
            return None
        return self._to_run(session, record)

    def _list(self, session: Session) -> list[ReplayRun]:
        query = select(ReplayRunRecord).order_by(ReplayRunRecord.started_at.desc())
        return [self._to_run(session, record) for record in session.scalars(query).all()]

    def _to_run(self, session: Session, record: ReplayRunRecord) -> ReplayRun:
        payload = deserialize_payload(record.payload_json)
        payload["started_at"] = ensure_aware_datetime(payload.get("started_at"))
        payload["completed_at"] = ensure_aware_datetime(payload.get("completed_at"))
        payload["trades"] = [
            ReplayTradeResult(
                **{
                    **item,
                    "opened_at": ensure_aware_datetime(item.get("opened_at")),
                    "closed_at": ensure_aware_datetime(item.get("closed_at")),
                }
            )
            for item in payload.get("trades", [])
        ]
        metrics_payload = payload.get("metrics")
        if metrics_payload is not None:
            metrics_payload["equity_curve"] = [
                EquityPoint(
                    timestamp=ensure_aware_datetime(item.get("timestamp")),
                    equity=float(item.get("equity", 0.0)),
                    realized_pnl=float(item.get("realized_pnl", 0.0)),
                    unrealized_pnl=float(item.get("unrealized_pnl", 0.0)),
                )
                for item in metrics_payload.get("equity_curve", [])
            ]
            payload["metrics"] = ReplayMetrics(**metrics_payload)
        fidelity_record = session.get(ReplayFidelityMetadataRecord, record.run_id)
        if fidelity_record is not None:
            fidelity_payload = deserialize_payload(fidelity_record.payload_json)
            fidelity_payload["generated_at"] = ensure_aware_datetime(fidelity_payload.get("generated_at"))
            payload["fidelity_metadata"] = ReplayFidelityMetadata(**fidelity_payload)
        return ReplayRun(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], ReplayRun | list[ReplayRun] | None]) -> ReplayRun | list[ReplayRun] | None:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

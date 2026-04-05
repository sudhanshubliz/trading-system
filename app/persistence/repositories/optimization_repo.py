from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.optimization.types import OptimizationResultRow, OptimizationRunResult, WalkForwardFoldResult
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import OptimizationRunRecord


class OptimizationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_optimization_run(self, run: OptimizationRunResult, *, session: Session | None = None) -> OptimizationRunResult:
        return self._with_session(session, lambda db: self._upsert(db, run))

    def get_optimization_run(self, run_id: str, *, session: Session | None = None) -> OptimizationRunResult | None:
        return self._with_session(session, lambda db: self._get(db, run_id))

    def list_runs(self, *, session: Session | None = None) -> list[OptimizationRunResult]:
        return self._with_session(session, self._list) or []

    def _upsert(self, session: Session, run: OptimizationRunResult) -> OptimizationRunResult:
        now = utc_now()
        record = session.get(OptimizationRunRecord, run.run_id)
        payload = asdict(run)
        if record is None:
            record = OptimizationRunRecord(
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
        return run

    def _get(self, session: Session, run_id: str) -> OptimizationRunResult | None:
        record = session.get(OptimizationRunRecord, run_id)
        if record is None:
            return None
        return self._to_run(record)

    def _list(self, session: Session) -> list[OptimizationRunResult]:
        query = select(OptimizationRunRecord).order_by(OptimizationRunRecord.started_at.desc())
        return [self._to_run(record) for record in session.scalars(query).all()]

    def _to_run(self, record: OptimizationRunRecord) -> OptimizationRunResult:
        payload = deserialize_payload(record.payload_json)
        payload["started_at"] = ensure_aware_datetime(payload.get("started_at"))
        payload["completed_at"] = ensure_aware_datetime(payload.get("completed_at"))
        leaderboard: list[OptimizationResultRow] = []
        for item in payload.get("leaderboard", []):
            item["walk_forward_results"] = [
                WalkForwardFoldResult(
                    fold_index=int(fold.get("fold_index", 0)),
                    train_start=ensure_aware_datetime(fold.get("train_start")),
                    train_end=ensure_aware_datetime(fold.get("train_end")),
                    test_start=ensure_aware_datetime(fold.get("test_start")),
                    test_end=ensure_aware_datetime(fold.get("test_end")),
                    metrics=fold.get("metrics", {}),
                )
                for fold in item.get("walk_forward_results", [])
            ]
            leaderboard.append(OptimizationResultRow(**item))
        payload["leaderboard"] = leaderboard
        return OptimizationRunResult(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], OptimizationRunResult | list[OptimizationRunResult] | None]) -> OptimizationRunResult | list[OptimizationRunResult] | None:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import BackfillJobRecord, ExperimentArtifactRecord, ExperimentRunRecord, ResearchExperimentRecord
from app.research.types import BackfillJob, ExperimentArtifact, ExperimentRun, ResearchExperiment


class ResearchRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_experiment(self, experiment: ResearchExperiment, *, session: Session | None = None) -> ResearchExperiment:
        return self._with_session(session, lambda db: self._upsert_experiment(db, experiment))

    def get_experiment(self, experiment_id: str, *, session: Session | None = None) -> ResearchExperiment | None:
        return self._with_session(session, lambda db: self._get_experiment(db, experiment_id))

    def list_experiments(self, *, limit: int = 100, session: Session | None = None) -> list[ResearchExperiment]:
        return self._with_session(session, lambda db: self._list_experiments(db, limit=limit)) or []

    def upsert_run(self, run: ExperimentRun, *, session: Session | None = None) -> ExperimentRun:
        return self._with_session(session, lambda db: self._upsert_run(db, run))

    def get_run(self, run_id: str, *, session: Session | None = None) -> ExperimentRun | None:
        return self._with_session(session, lambda db: self._get_run(db, run_id))

    def list_runs(self, *, limit: int = 100, session: Session | None = None) -> list[ExperimentRun]:
        return self._with_session(session, lambda db: self._list_runs(db, limit=limit)) or []

    def upsert_artifact(self, artifact: ExperimentArtifact, *, session: Session | None = None) -> ExperimentArtifact:
        return self._with_session(session, lambda db: self._upsert_artifact(db, artifact))

    def list_artifacts_for_run(self, run_id: str, *, session: Session | None = None) -> list[ExperimentArtifact]:
        return self._with_session(session, lambda db: self._list_artifacts(db, run_id=run_id)) or []

    def upsert_backfill_job(self, item: BackfillJob, *, session: Session | None = None) -> BackfillJob:
        return self._with_session(session, lambda db: self._upsert_backfill_job(db, item))

    def get_backfill_job(self, job_id: str, *, session: Session | None = None) -> BackfillJob | None:
        return self._with_session(session, lambda db: self._get_backfill_job(db, job_id))

    def list_backfill_jobs(self, *, limit: int = 100, session: Session | None = None) -> list[BackfillJob]:
        return self._with_session(session, lambda db: self._list_backfill_jobs(db, limit=limit)) or []

    def _upsert_experiment(self, session: Session, experiment: ResearchExperiment) -> ResearchExperiment:
        record = session.get(ResearchExperimentRecord, experiment.experiment_id)
        payload = serialize_payload(experiment)
        if record is None:
            session.add(
                ResearchExperimentRecord(
                    experiment_id=experiment.experiment_id,
                    experiment_name=experiment.experiment_name,
                    strategy_family=experiment.strategy_family,
                    status=experiment.status,
                    created_at=experiment.created_at,
                    updated_at=experiment.updated_at,
                    payload_json=payload,
                )
            )
        else:
            record.experiment_name = experiment.experiment_name
            record.strategy_family = experiment.strategy_family
            record.status = experiment.status
            record.updated_at = experiment.updated_at
            record.payload_json = payload
        return experiment

    def _get_experiment(self, session: Session, experiment_id: str) -> ResearchExperiment | None:
        record = session.get(ResearchExperimentRecord, experiment_id)
        if record is None:
            return None
        payload = deserialize_payload(record.payload_json)
        payload["created_at"] = ensure_aware_datetime(payload.get("created_at"))
        payload["updated_at"] = ensure_aware_datetime(payload.get("updated_at"))
        return ResearchExperiment(**payload)

    def _list_experiments(self, session: Session, *, limit: int) -> list[ResearchExperiment]:
        query = select(ResearchExperimentRecord).order_by(ResearchExperimentRecord.updated_at.desc()).limit(max(limit, 0))
        return [self._get_experiment(session, record.experiment_id) for record in session.scalars(query).all()]

    def _upsert_run(self, session: Session, run: ExperimentRun) -> ExperimentRun:
        now = utc_now()
        record = session.get(ExperimentRunRecord, run.run_id)
        payload = serialize_payload(run)
        if record is None:
            session.add(
                ExperimentRunRecord(
                    run_id=run.run_id,
                    experiment_id=run.experiment_id,
                    status=run.status,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    payload_json=payload,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            record.experiment_id = run.experiment_id
            record.status = run.status
            record.started_at = run.started_at
            record.completed_at = run.completed_at
            record.payload_json = payload
            record.updated_at = now
        return run

    def _get_run(self, session: Session, run_id: str) -> ExperimentRun | None:
        record = session.get(ExperimentRunRecord, run_id)
        if record is None:
            return None
        payload = deserialize_payload(record.payload_json)
        payload["started_at"] = ensure_aware_datetime(payload.get("started_at"))
        payload["completed_at"] = ensure_aware_datetime(payload.get("completed_at"))
        return ExperimentRun(**payload)

    def _list_runs(self, session: Session, *, limit: int) -> list[ExperimentRun]:
        query = select(ExperimentRunRecord).order_by(ExperimentRunRecord.started_at.desc()).limit(max(limit, 0))
        return [self._get_run(session, record.run_id) for record in session.scalars(query).all()]

    def _upsert_artifact(self, session: Session, artifact: ExperimentArtifact) -> ExperimentArtifact:
        record = session.get(ExperimentArtifactRecord, artifact.artifact_id)
        payload = serialize_payload(artifact)
        if record is None:
            session.add(
                ExperimentArtifactRecord(
                    artifact_id=artifact.artifact_id,
                    run_id=artifact.run_id,
                    artifact_type=artifact.artifact_type,
                    uri=artifact.uri,
                    created_at=artifact.created_at,
                    payload_json=payload,
                )
            )
        else:
            record.run_id = artifact.run_id
            record.artifact_type = artifact.artifact_type
            record.uri = artifact.uri
            record.payload_json = payload
        return artifact

    def _list_artifacts(self, session: Session, *, run_id: str) -> list[ExperimentArtifact]:
        query = (
            select(ExperimentArtifactRecord)
            .where(ExperimentArtifactRecord.run_id == run_id)
            .order_by(ExperimentArtifactRecord.created_at.desc())
        )
        items: list[ExperimentArtifact] = []
        for record in session.scalars(query).all():
            payload = deserialize_payload(record.payload_json)
            payload["created_at"] = ensure_aware_datetime(payload.get("created_at"))
            items.append(ExperimentArtifact(**payload))
        return items

    def _upsert_backfill_job(self, session: Session, item: BackfillJob) -> BackfillJob:
        record = session.get(BackfillJobRecord, item.job_id)
        payload = serialize_payload(item)
        if record is None:
            session.add(
                BackfillJobRecord(
                    job_id=item.job_id,
                    dataset_type=item.dataset_type,
                    provider_name=item.provider_name,
                    status=item.status,
                    started_at=item.started_at,
                    finished_at=item.finished_at,
                    payload_json=payload,
                )
            )
        else:
            record.dataset_type = item.dataset_type
            record.provider_name = item.provider_name
            record.status = item.status
            record.started_at = item.started_at
            record.finished_at = item.finished_at
            record.payload_json = payload
        return item

    def _get_backfill_job(self, session: Session, job_id: str) -> BackfillJob | None:
        record = session.get(BackfillJobRecord, job_id)
        if record is None:
            return None
        payload = deserialize_payload(record.payload_json)
        payload["started_at"] = ensure_aware_datetime(payload.get("started_at"))
        payload["finished_at"] = ensure_aware_datetime(payload.get("finished_at"))
        return BackfillJob(**payload)

    def _list_backfill_jobs(self, session: Session, *, limit: int) -> list[BackfillJob]:
        query = select(BackfillJobRecord).order_by(BackfillJobRecord.started_at.desc()).limit(max(limit, 0))
        return [self._get_backfill_job(session, record.job_id) for record in session.scalars(query).all()]

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

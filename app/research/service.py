from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone

from app.config.settings import Settings, get_settings
from app.persistence.repositories.research_repo import ResearchRepository
from app.research.types import BackfillJob, ExperimentArtifact, ExperimentRun, ResearchExperiment


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        research_repo: ResearchRepository | None = None,
        polymarket_service: object | None = None,
        wallet_intel_service: object | None = None,
        event_signals_service: object | None = None,
        provider_health_service: object | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.research_repo = research_repo
        self.polymarket_service = polymarket_service
        self.wallet_intel_service = wallet_intel_service
        self.event_signals_service = event_signals_service
        self.provider_health_service = provider_health_service

    def bootstrap_defaults(self) -> None:
        if self.research_repo is None:
            return
        now = utc_now()
        default_id = "phase1-default-experiment"
        if self.research_repo.get_experiment(default_id) is not None:
            return
        experiment = ResearchExperiment(
            experiment_id=default_id,
            experiment_name="Phase 1 Feature and Fusion Baseline",
            strategy_family="research_platform",
            status="active",
            created_at=now,
            updated_at=now,
            metadata={
                "description": "Baseline research track for feature, regime, and alpha fusion iteration.",
                "stage": "research_only",
            },
        )
        run = ExperimentRun(
            run_id="phase1-default-run",
            experiment_id=default_id,
            status="ready",
            started_at=now,
            completed_at=None,
            metrics={},
            metadata={"note": "Seeded automatically for dashboard visibility."},
        )
        artifact = ExperimentArtifact(
            artifact_id="phase1-default-artifact",
            run_id=run.run_id,
            artifact_type="doc",
            uri="docs/feature_engine.md",
            created_at=now,
            metadata={"label": "Feature engine design"},
        )
        self.research_repo.upsert_experiment(experiment)
        self.research_repo.upsert_run(run)
        self.research_repo.upsert_artifact(artifact)

    def list_experiments(self, limit: int | None = None) -> list[ResearchExperiment]:
        if self.research_repo is None:
            return []
        return self.research_repo.list_experiments(limit=limit or self.settings.research_store_limit)

    def get_experiment(self, experiment_id: str) -> ResearchExperiment | None:
        if self.research_repo is None:
            return None
        return self.research_repo.get_experiment(experiment_id)

    def list_runs(self, limit: int | None = None) -> list[ExperimentRun]:
        if self.research_repo is None:
            return []
        return self.research_repo.list_runs(limit=limit or self.settings.research_store_limit)

    def get_run(self, run_id: str) -> ExperimentRun | None:
        if self.research_repo is None:
            return None
        return self.research_repo.get_run(run_id)

    async def run_backfill_job(
        self,
        *,
        dataset_type: str,
        provider_name: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        force: bool = False,
        notes: list[str] | None = None,
    ) -> BackfillJob:
        started_at = utc_now()
        job_id = self._build_backfill_job_id(dataset_type=dataset_type, provider_name=provider_name, start_time=start_time, end_time=end_time)
        existing = self.get_backfill_job(job_id)
        if existing is not None and existing.status == "completed" and not force:
            return existing

        job = BackfillJob(
            job_id=job_id,
            dataset_type=dataset_type,
            provider_name=provider_name,
            time_range={
                "start_time": start_time.isoformat() if start_time is not None else None,
                "end_time": end_time.isoformat() if end_time is not None else None,
            },
            status="running",
            records_requested=0,
            records_written=0,
            started_at=started_at,
            finished_at=None,
            notes=notes or [],
            metadata={"resume_enabled": self.settings.backfill_resume_enabled, "force": force},
        )
        self._upsert_backfill_job(job)

        try:
            records_written = await self._execute_backfill(dataset_type=dataset_type)
            completed = replace(
                job,
                status="completed",
                records_requested=records_written,
                records_written=records_written,
                finished_at=utc_now(),
            )
            self._upsert_backfill_job(completed)
            return completed
        except Exception as exc:
            failed = replace(
                job,
                status="failed",
                finished_at=utc_now(),
                error_summary=str(exc),
            )
            self._upsert_backfill_job(failed)
            raise

    def list_backfill_jobs(self, *, limit: int | None = None) -> list[BackfillJob]:
        if self.research_repo is None:
            return []
        return self.research_repo.list_backfill_jobs(limit=limit or self.settings.research_store_limit)

    def get_backfill_job(self, job_id: str) -> BackfillJob | None:
        if self.research_repo is None:
            return None
        return self.research_repo.get_backfill_job(job_id)

    def summarize_backfill_status(self) -> dict[str, object]:
        items = self.list_backfill_jobs(limit=20)
        return {
            "count": len(items),
            "recent_jobs": items,
            "failed": len([item for item in items if item.status == "failed"]),
            "running": len([item for item in items if item.status == "running"]),
            "completed": len([item for item in items if item.status == "completed"]),
        }

    async def _execute_backfill(self, *, dataset_type: str) -> int:
        if not self.settings.enable_backfill_jobs:
            return 0
        if dataset_type == "polymarket_markets" and self.polymarket_service is not None:
            await self.polymarket_service.refresh()
            return len(await self.polymarket_service.list_markets())
        if dataset_type == "polymarket_opportunities" and self.polymarket_service is not None:
            return len(await self.polymarket_service.evaluate_opportunities())
        if dataset_type == "wallet_observations" and self.wallet_intel_service is not None:
            await self.wallet_intel_service.refresh()
            return len(self.wallet_intel_service.list_observations(limit=self.settings.backfill_batch_size))
        if dataset_type == "event_observations" and self.event_signals_service is not None:
            await self.event_signals_service.refresh()
            return len(await self.event_signals_service.list_events())
        raise ValueError(f"unsupported_backfill_dataset:{dataset_type}")

    def _upsert_backfill_job(self, item: BackfillJob) -> None:
        if self.research_repo is not None:
            self.research_repo.upsert_backfill_job(item)

    def _build_backfill_job_id(
        self,
        *,
        dataset_type: str,
        provider_name: str,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> str:
        seed = "|".join(
            [
                dataset_type,
                provider_name,
                start_time.isoformat() if start_time is not None else "",
                end_time.isoformat() if end_time is not None else "",
            ]
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        return f"bfj_{digest[:12]}"

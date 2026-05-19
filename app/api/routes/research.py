from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.research import (
    BackfillJobListResponse,
    BackfillJobRequest,
    BackfillJobResponse,
    ExperimentArtifactResponse,
    ExperimentRunListResponse,
    ExperimentRunResponse,
    ResearchExperimentListResponse,
    ResearchExperimentResponse,
)

router = APIRouter(prefix="/research")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_research_service(request: Request) -> Any:
    service = getattr(request.app.state, "research_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Research service is unavailable")
    return service


@router.get("/experiments", response_model=ResearchExperimentListResponse)
async def list_experiments(request: Request, limit: int | None = Query(default=20, ge=1)) -> ResearchExperimentListResponse:
    service = _get_research_service(request)
    items = []
    for experiment in service.list_experiments(limit=limit):
        payload = _serialize(experiment)
        artifacts = []
        if service.research_repo is not None:
            for run in service.list_runs(limit=100):
                if run.experiment_id != experiment.experiment_id:
                    continue
                artifacts.extend(service.research_repo.list_artifacts_for_run(run.run_id))
        payload["artifacts"] = [_serialize(item) for item in artifacts]
        items.append(ResearchExperimentResponse.model_validate(payload))
    return ResearchExperimentListResponse(items=items, count=len(items))


@router.get("/experiments/{experiment_id}", response_model=ResearchExperimentResponse)
async def get_experiment(experiment_id: str, request: Request) -> ResearchExperimentResponse:
    service = _get_research_service(request)
    experiment = service.get_experiment(experiment_id)
    if experiment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    payload = _serialize(experiment)
    artifacts = []
    if service.research_repo is not None:
        for run in service.list_runs(limit=100):
            if run.experiment_id != experiment_id:
                continue
            artifacts.extend(service.research_repo.list_artifacts_for_run(run.run_id))
    payload["artifacts"] = [ExperimentArtifactResponse.model_validate(_serialize(item)) for item in artifacts]
    return ResearchExperimentResponse.model_validate(payload)


@router.get("/runs", response_model=ExperimentRunListResponse)
async def list_runs(request: Request, limit: int | None = Query(default=20, ge=1)) -> ExperimentRunListResponse:
    service = _get_research_service(request)
    items = []
    for run in service.list_runs(limit=limit):
        payload = _serialize(run)
        payload["artifacts"] = [
            _serialize(item) for item in (service.research_repo.list_artifacts_for_run(run.run_id) if service.research_repo else [])
        ]
        items.append(ExperimentRunResponse.model_validate(payload))
    return ExperimentRunListResponse(items=items, count=len(items))


@router.get("/runs/{run_id}", response_model=ExperimentRunResponse)
async def get_run(run_id: str, request: Request) -> ExperimentRunResponse:
    service = _get_research_service(request)
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    payload = _serialize(run)
    payload["artifacts"] = [
        _serialize(item) for item in (service.research_repo.list_artifacts_for_run(run.run_id) if service.research_repo else [])
    ]
    return ExperimentRunResponse.model_validate(payload)


@router.post("/backfill-jobs", response_model=BackfillJobResponse)
async def run_backfill_job(payload: BackfillJobRequest, request: Request) -> BackfillJobResponse:
    service = _get_research_service(request)
    job = await service.run_backfill_job(
        dataset_type=payload.dataset_type,
        provider_name=payload.provider_name,
        start_time=payload.start_time,
        end_time=payload.end_time,
        force=payload.force,
        notes=payload.notes,
    )
    return BackfillJobResponse.model_validate(_serialize(job))


@router.get("/backfill-jobs", response_model=BackfillJobListResponse)
async def list_backfill_jobs(request: Request, limit: int | None = Query(default=20, ge=1)) -> BackfillJobListResponse:
    service = _get_research_service(request)
    items = [BackfillJobResponse.model_validate(_serialize(item)) for item in service.list_backfill_jobs(limit=limit)]
    return BackfillJobListResponse(items=items, count=len(items))


@router.get("/backfill-jobs/{job_id}", response_model=BackfillJobResponse)
async def get_backfill_job(job_id: str, request: Request) -> BackfillJobResponse:
    service = _get_research_service(request)
    job = service.get_backfill_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backfill job not found")
    return BackfillJobResponse.model_validate(_serialize(job))

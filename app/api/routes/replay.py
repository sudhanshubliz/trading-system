from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.replay import ReplayMetricsResponse, ReplayRunListResponse, ReplayRunRequest, ReplayRunResponse

router = APIRouter(prefix="/replay")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_replay_service(request: Request) -> Any:
    service = getattr(request.app.state, "replay_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Replay service is unavailable",
        )
    return service


@router.post("/run", response_model=ReplayRunResponse)
async def run_replay(payload: ReplayRunRequest, request: Request) -> ReplayRunResponse:
    service = _get_replay_service(request)
    run = await service.run_replay(
        candles_source=payload.model_dump()["candles"],
        futures_candles_source=payload.model_dump()["futures_candles"],
        symbols=payload.symbols,
        initial_balance=payload.initial_balance,
        fidelity_mode=payload.fidelity_mode,
        allow_partial_external_data=payload.allow_partial_external_data,
        polymarket_snapshots=payload.polymarket_snapshots,
        event_observations=payload.event_observations,
        wallet_observations=payload.wallet_observations,
    )
    return ReplayRunResponse.model_validate(_serialize(run))


@router.get("/runs", response_model=ReplayRunListResponse)
async def list_replay_runs(request: Request) -> ReplayRunListResponse:
    service = _get_replay_service(request)
    runs = service.list_runs()
    serialized = [ReplayRunResponse.model_validate(_serialize(run)) for run in runs]
    return ReplayRunListResponse(items=serialized, count=len(serialized))


@router.get("/runs/{run_id}", response_model=ReplayRunResponse)
async def get_replay_run(run_id: str, request: Request) -> ReplayRunResponse:
    service = _get_replay_service(request)
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replay run not found")
    return ReplayRunResponse.model_validate(_serialize(run))


@router.get("/runs/{run_id}/metrics", response_model=ReplayMetricsResponse)
async def get_replay_metrics(run_id: str, request: Request) -> ReplayMetricsResponse:
    service = _get_replay_service(request)
    metrics = service.get_metrics(run_id)
    if metrics is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replay run not found")
    return ReplayMetricsResponse.model_validate(_serialize(metrics))

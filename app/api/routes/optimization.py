from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.optimization import (
    OptimizationLeaderboardResponse,
    OptimizationResultRowResponse,
    OptimizationRunListResponse,
    OptimizationRunRequest,
    OptimizationRunResponse,
)

router = APIRouter(prefix="/optimization")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_optimization_service(request: Request) -> Any:
    service = getattr(request.app.state, "optimization_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Optimization service is unavailable",
        )
    return service


def _to_run_response(run: Any) -> OptimizationRunResponse:
    payload = _serialize(run)
    payload.pop("leaderboard", None)
    return OptimizationRunResponse.model_validate(payload)


@router.post("/run", response_model=OptimizationRunResponse)
async def run_optimization(payload: OptimizationRunRequest, request: Request) -> OptimizationRunResponse:
    service = _get_optimization_service(request)
    run = await service.run_optimization(payload)
    return _to_run_response(run)


@router.get("/runs", response_model=OptimizationRunListResponse)
async def list_optimization_runs(request: Request) -> OptimizationRunListResponse:
    service = _get_optimization_service(request)
    runs = service.list_runs()
    serialized = [_to_run_response(run) for run in runs]
    return OptimizationRunListResponse(items=serialized, count=len(serialized))


@router.get("/runs/{run_id}", response_model=OptimizationRunResponse)
async def get_optimization_run(run_id: str, request: Request) -> OptimizationRunResponse:
    service = _get_optimization_service(request)
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Optimization run not found")
    return _to_run_response(run)


@router.get("/runs/{run_id}/leaderboard", response_model=OptimizationLeaderboardResponse)
async def get_optimization_leaderboard(
    run_id: str,
    request: Request,
    top_n: int | None = Query(default=None, ge=1),
) -> OptimizationLeaderboardResponse:
    service = _get_optimization_service(request)
    rows = service.get_leaderboard(run_id, top_n=top_n)
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Optimization run not found")
    serialized = [OptimizationResultRowResponse.model_validate(_serialize(row)) for row in rows]
    return OptimizationLeaderboardResponse(items=serialized, count=len(serialized))

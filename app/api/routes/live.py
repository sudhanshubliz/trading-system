from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.live import (
    LiveExecutionResponse,
    LiveLockListResponse,
    LiveStatusResponse,
    LiveReconciliationResponse,
)

router = APIRouter(prefix="/live")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_live_controller(request: Request) -> Any:
    service = getattr(request.app.state, "live_controller", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live controller is unavailable",
        )
    return service


@router.get("/status", response_model=LiveStatusResponse)
async def get_live_status(request: Request) -> LiveStatusResponse:
    controller = _get_live_controller(request)
    return LiveStatusResponse.model_validate(_serialize(await controller.get_live_status()))


@router.post("/arm", response_model=LiveStatusResponse)
async def arm_live(request: Request) -> LiveStatusResponse:
    controller = _get_live_controller(request)
    return LiveStatusResponse.model_validate(_serialize(await controller.arm_live_trading()))


@router.post("/disarm", response_model=LiveStatusResponse)
async def disarm_live(request: Request) -> LiveStatusResponse:
    controller = _get_live_controller(request)
    return LiveStatusResponse.model_validate(_serialize(await controller.disarm_live_trading()))


@router.get("/locks", response_model=LiveLockListResponse)
async def list_live_locks(request: Request) -> LiveLockListResponse:
    controller = _get_live_controller(request)
    items = controller.list_locks()
    serialized = _serialize(items)
    return LiveLockListResponse(items=serialized, count=len(serialized))


@router.post("/locks/{lock_id}/clear", response_model=LiveStatusResponse)
async def clear_live_lock(lock_id: str, request: Request) -> LiveStatusResponse:
    controller = _get_live_controller(request)
    return LiveStatusResponse.model_validate(_serialize(await controller.clear_lock(lock_id)))


@router.post("/execute/{assessment_id}", response_model=LiveExecutionResponse)
async def execute_live(assessment_id: str, request: Request) -> LiveExecutionResponse:
    controller = _get_live_controller(request)
    result = await controller.execute_live_trade(assessment_id)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_serialize(result),
        )
    return LiveExecutionResponse.model_validate(_serialize(result))


@router.post("/reconcile", response_model=LiveReconciliationResponse)
async def reconcile_live(request: Request) -> LiveReconciliationResponse:
    controller = _get_live_controller(request)
    result = await controller.reconcile()
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_serialize(result),
        )
    return LiveReconciliationResponse.model_validate(_serialize(result))

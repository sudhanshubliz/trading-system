from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.execution import ControlStatusResponse

router = APIRouter(prefix="/control")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_execution_service(request: Request) -> Any:
    service = getattr(request.app.state, "execution_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Execution service is unavailable",
        )
    return service


@router.post("/pause", response_model=ControlStatusResponse)
async def pause_execution(request: Request) -> ControlStatusResponse:
    service = _get_execution_service(request)
    status_payload = await service.pause()
    live_controller = getattr(request.app.state, "live_controller", None)
    if live_controller is not None:
        await live_controller.get_live_status()
    return ControlStatusResponse.model_validate(_serialize(status_payload))


@router.post("/resume", response_model=ControlStatusResponse)
async def resume_execution(request: Request) -> ControlStatusResponse:
    service = _get_execution_service(request)
    status_payload = await service.resume()
    live_controller = getattr(request.app.state, "live_controller", None)
    if live_controller is not None:
        await live_controller.get_live_status()
    return ControlStatusResponse.model_validate(_serialize(status_payload))


@router.get("/status", response_model=ControlStatusResponse)
async def get_control_status(request: Request) -> ControlStatusResponse:
    service = _get_execution_service(request)
    status_payload = await service.get_control_status_synced()
    return ControlStatusResponse.model_validate(_serialize(status_payload))

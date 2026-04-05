from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.config.settings import get_settings
from app.schemas.rollout import (
    RolloutCapitalResponse,
    RolloutHistoryResponse,
    RolloutStatusResponse,
)

router = APIRouter(prefix="/rollout")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_rollout_service(request: Request) -> Any:
    service = getattr(request.app.state, "rollout_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rollout service is unavailable",
        )
    return service


def _build_status_payload(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    live_controller = getattr(request.app.state, "live_controller", None)
    live_effectively_allowed = bool(
        settings.enable_live_trading
        and payload.get("current_phase") != "disabled"
        and not payload.get("rollback_active", False)
    )
    if live_controller is not None and hasattr(live_controller, "_is_armed"):
        live_effectively_allowed = live_effectively_allowed and bool(live_controller._is_armed())
    return {
        **payload,
        "live_effectively_allowed": live_effectively_allowed,
    }


@router.get("/status", response_model=RolloutStatusResponse)
async def get_rollout_status(request: Request) -> RolloutStatusResponse:
    service = _get_rollout_service(request)
    payload = _build_status_payload(request, service.get_capital_status())
    return RolloutStatusResponse.model_validate(_serialize(payload))


@router.post("/phase/{phase}", response_model=RolloutStatusResponse)
async def set_rollout_phase(phase: str, request: Request) -> RolloutStatusResponse:
    service = _get_rollout_service(request)
    try:
        service.set_rollout_phase(phase, changed_by="api", reason=f"api_set_phase_{phase}")
    except ValueError as exc:
        detail = str(exc)
        if detail == "invalid_rollout_phase":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reasons": [item for item in detail.split(",") if item]},
        ) from exc
    payload = _build_status_payload(request, service.get_capital_status())
    return RolloutStatusResponse.model_validate(_serialize(payload))


@router.post("/scale-up", response_model=RolloutStatusResponse)
async def scale_up_rollout(request: Request) -> RolloutStatusResponse:
    service = _get_rollout_service(request)
    try:
        service.scale_up(changed_by="api", reason="api_scale_up")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reasons": [item for item in str(exc).split(",") if item]},
        ) from exc
    payload = _build_status_payload(request, service.get_capital_status())
    return RolloutStatusResponse.model_validate(_serialize(payload))


@router.post("/scale-down", response_model=RolloutStatusResponse)
async def scale_down_rollout(request: Request) -> RolloutStatusResponse:
    service = _get_rollout_service(request)
    service.scale_down(changed_by="api", reason="api_scale_down")
    payload = _build_status_payload(request, service.get_capital_status())
    return RolloutStatusResponse.model_validate(_serialize(payload))


@router.post("/rollback", response_model=RolloutStatusResponse)
async def rollback_rollout(request: Request) -> RolloutStatusResponse:
    service = _get_rollout_service(request)
    service.rollback_live(changed_by="api", reason="api_manual_rollback")
    payload = _build_status_payload(request, service.get_capital_status())
    return RolloutStatusResponse.model_validate(_serialize(payload))


@router.get("/history", response_model=RolloutHistoryResponse)
async def get_rollout_history(request: Request) -> RolloutHistoryResponse:
    service = _get_rollout_service(request)
    items = _serialize(service.list_phase_history())
    return RolloutHistoryResponse(items=items, count=len(items))


@router.get("/capital", response_model=RolloutCapitalResponse)
async def get_rollout_capital(request: Request) -> RolloutCapitalResponse:
    service = _get_rollout_service(request)
    payload = service.get_capital_status()
    return RolloutCapitalResponse.model_validate(_serialize(payload))

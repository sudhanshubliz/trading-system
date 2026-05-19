from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.provider_health import ProviderHealthListResponse, ProviderHealthResponse, ProviderHealthSummaryResponse

router = APIRouter(prefix="/provider-health")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    service = getattr(request.app.state, "provider_health_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Provider health service is unavailable")
    return service


@router.get("", response_model=ProviderHealthListResponse)
async def list_provider_health(request: Request) -> ProviderHealthListResponse:
    service = _get_service(request)
    items = service.list_latest()
    serialized = [ProviderHealthResponse.model_validate(_serialize(item)) for item in items]
    return ProviderHealthListResponse(items=serialized, count=len(serialized))


@router.get("/summary", response_model=ProviderHealthSummaryResponse)
async def get_provider_health_summary(request: Request) -> ProviderHealthSummaryResponse:
    service = _get_service(request)
    summary = _serialize(service.build_summary())
    return ProviderHealthSummaryResponse.model_validate(summary)


@router.get("/{provider_name}", response_model=ProviderHealthResponse)
async def get_provider_health(provider_name: str, request: Request) -> ProviderHealthResponse:
    service = _get_service(request)
    item = service.get_provider(provider_name)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider health not found")
    return ProviderHealthResponse.model_validate(_serialize(item))

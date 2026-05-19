from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.event_signals import EventListResponse, EventSignalListResponse, EventSignalResponse, NormalizedEventResponse
from app.schemas.provider_health import ProviderHealthResponse

router = APIRouter(prefix="/events")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    service = getattr(request.app.state, "event_signals_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Event signals service is unavailable")
    return service


@router.get("", response_model=EventListResponse)
async def list_events(request: Request) -> EventListResponse:
    service = _get_service(request)
    items = await service.list_events()
    serialized = [NormalizedEventResponse.model_validate(_serialize(item)) for item in items]
    return EventListResponse(items=serialized, count=len(serialized))


@router.get("/signals", response_model=EventSignalListResponse)
async def list_event_signals(request: Request) -> EventSignalListResponse:
    service = _get_service(request)
    items = service.list_signals(limit=100)
    serialized = [EventSignalResponse.model_validate(_serialize(item)) for item in items]
    return EventSignalListResponse(items=serialized, count=len(serialized))


@router.get("/providers/health", response_model=ProviderHealthResponse)
async def get_event_provider_health(request: Request) -> ProviderHealthResponse:
    service = _get_service(request)
    payload = await service.get_provider_health()
    return ProviderHealthResponse.model_validate(
        {
            "snapshot_id": "event_provider_live",
            "provider_name": "event_signals",
            "status": payload.get("status", "degraded"),
            "latency_ms": payload.get("latency_ms"),
            "success_rate": payload.get("success_rate", 0.0),
            "stale_data_flag": payload.get("stale_data_flag", False),
            "error_count": payload.get("error_count", 0),
            "last_success_at": payload.get("last_success_at"),
            "last_failure_at": payload.get("last_failure_at"),
            "observed_at": payload.get("observed_at") or __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            "notes": payload.get("notes", []),
            "metadata": payload.get("metadata", {}),
        }
    )


@router.get("/{event_id}", response_model=NormalizedEventResponse)
async def get_event(event_id: str, request: Request) -> NormalizedEventResponse:
    service = _get_service(request)
    item = await service.get_event(event_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return NormalizedEventResponse.model_validate(_serialize(item))

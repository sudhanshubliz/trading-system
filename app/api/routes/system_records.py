from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.system_records import (
    AlertHistoryListResponse,
    AlertHistoryResponse,
    IncidentCreateRequest,
    IncidentListResponse,
    IncidentResponse,
    IncidentUpdateRequest,
    OperatorNoteListResponse,
    OperatorNoteRequest,
    OperatorNoteResponse,
)

router = APIRouter(prefix="/system")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    return request.app.state.openclaw_bridge


@router.get("/operator-notes", response_model=OperatorNoteListResponse)
async def list_operator_notes(request: Request, limit: int = Query(default=50, ge=1)) -> OperatorNoteListResponse:
    items = _get_service(request).list_operator_notes(limit=limit)
    serialized = [OperatorNoteResponse.model_validate(_serialize(item)) for item in items]
    return OperatorNoteListResponse(items=serialized, count=len(serialized))


@router.post("/operator-notes", response_model=OperatorNoteResponse)
async def create_operator_note(payload: OperatorNoteRequest, request: Request) -> OperatorNoteResponse:
    item = _get_service(request).add_operator_note(
        related_entity_id=payload.related_entity_id,
        note=payload.note,
        note_type=payload.note_type,
        metadata=payload.metadata,
    )
    return OperatorNoteResponse.model_validate(_serialize(item))


@router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(request: Request, limit: int = Query(default=50, ge=1)) -> IncidentListResponse:
    items = _get_service(request).list_incidents(limit=limit)
    serialized = [IncidentResponse.model_validate(_serialize(item)) for item in items]
    return IncidentListResponse(items=serialized, count=len(serialized))


@router.post("/incidents", response_model=IncidentResponse)
async def create_incident(payload: IncidentCreateRequest, request: Request) -> IncidentResponse:
    item = _get_service(request).create_incident(**payload.model_dump())
    return IncidentResponse.model_validate(_serialize(item))


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str, request: Request) -> IncidentResponse:
    item = _get_service(request).get_incident(incident_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return IncidentResponse.model_validate(_serialize(item))


@router.post("/incidents/{incident_id}/acknowledge", response_model=IncidentResponse)
async def acknowledge_incident(incident_id: str, payload: IncidentUpdateRequest, request: Request) -> IncidentResponse:
    item = _get_service(request).acknowledge_incident(incident_id, note=payload.note, severity=payload.severity)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return IncidentResponse.model_validate(_serialize(item))


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentResponse)
async def resolve_incident(incident_id: str, payload: IncidentUpdateRequest, request: Request) -> IncidentResponse:
    item = _get_service(request).resolve_incident(incident_id, note=payload.note)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return IncidentResponse.model_validate(_serialize(item))


@router.get("/alerts/history", response_model=AlertHistoryListResponse)
async def list_alert_history(request: Request, limit: int = Query(default=50, ge=1)) -> AlertHistoryListResponse:
    items = _get_service(request).list_alert_history(limit=limit)
    serialized = [AlertHistoryResponse.model_validate(_serialize(item)) for item in items]
    return AlertHistoryListResponse(items=serialized, count=len(serialized))

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.ops import IncidentSummaryResponse, OperatorStatusResponse, RecoveryReportResponse

router = APIRouter(prefix="/ops")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_ops_service(request: Request) -> Any:
    service = getattr(request.app.state, "ops_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ops service is unavailable",
        )
    return service


@router.get("/status", response_model=OperatorStatusResponse)
async def get_ops_status(request: Request) -> OperatorStatusResponse:
    service = _get_ops_service(request)
    return OperatorStatusResponse.model_validate(_serialize(await service.get_operator_status()))


@router.get("/incidents", response_model=IncidentSummaryResponse)
async def get_ops_incidents(request: Request) -> IncidentSummaryResponse:
    service = _get_ops_service(request)
    return IncidentSummaryResponse.model_validate(_serialize(await service.get_incident_summary()))


@router.post("/recover", response_model=RecoveryReportResponse)
async def run_ops_recovery(request: Request) -> RecoveryReportResponse:
    service = _get_ops_service(request)
    try:
        result = await service.run_recovery()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if not result.ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_serialize(result))
    return RecoveryReportResponse.model_validate(_serialize(result))

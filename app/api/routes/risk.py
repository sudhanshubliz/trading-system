from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.risk import (
    RiskAssessmentResponse,
    RiskEvaluateSignalsRequest,
    RiskEvaluateSignalsResponse,
    RiskLockEventListResponse,
    RiskSummaryResponse,
    RiskValidateRequest,
)

router = APIRouter(prefix="/risk")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_risk_service(request: Request) -> Any:
    service = getattr(request.app.state, "risk_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Risk service is unavailable",
        )
    return service


@router.get("/summary", response_model=RiskSummaryResponse)
async def get_risk_summary(request: Request) -> RiskSummaryResponse:
    service = _get_risk_service(request)
    summary = service.get_summary()
    return RiskSummaryResponse.model_validate(_serialize(summary))


@router.post("/validate", response_model=RiskAssessmentResponse)
async def validate_risk(payload: RiskValidateRequest, request: Request) -> RiskAssessmentResponse:
    service = _get_risk_service(request)
    assessment = await service.validate_signal_payload(payload)
    return RiskAssessmentResponse.model_validate(_serialize(assessment))


@router.post("/evaluate-signals", response_model=RiskEvaluateSignalsResponse)
async def evaluate_signals_risk(
    payload: RiskEvaluateSignalsRequest,
    request: Request,
) -> RiskEvaluateSignalsResponse:
    service = _get_risk_service(request)
    items = await service.evaluate_signals(payload.symbols)
    serialized = [RiskAssessmentResponse.model_validate(_serialize(item)) for item in items]
    return RiskEvaluateSignalsResponse(items=serialized, count=len(serialized))


@router.get("/locks/current", response_model=RiskLockEventListResponse)
async def get_current_risk_locks(request: Request) -> RiskLockEventListResponse:
    service = _get_risk_service(request)
    items = service.list_current_locks()
    return RiskLockEventListResponse(items=items, count=len(items))


@router.get("/locks/history", response_model=RiskLockEventListResponse)
async def get_risk_lock_history(
    request: Request,
    limit: int = Query(default=50, ge=1),
) -> RiskLockEventListResponse:
    service = _get_risk_service(request)
    items = service.list_lock_history(limit=limit)
    return RiskLockEventListResponse(items=items, count=len(items))

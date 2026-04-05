from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, status

from app.schemas.execution import ApprovalListResponse, ApprovalResponse, RejectApprovalRequest

router = APIRouter(prefix="/approvals")


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


@router.get("", response_model=ApprovalListResponse)
async def get_approvals(request: Request) -> ApprovalListResponse:
    service = _get_execution_service(request)
    items = await service.list_approvals()
    serialized = [ApprovalResponse.model_validate(_serialize(item)) for item in items]
    return ApprovalListResponse(items=serialized, count=len(serialized))


@router.get("/pending", response_model=ApprovalListResponse)
async def get_pending_approvals(request: Request) -> ApprovalListResponse:
    service = _get_execution_service(request)
    items = await service.list_pending_approvals()
    serialized = [ApprovalResponse.model_validate(_serialize(item)) for item in items]
    return ApprovalListResponse(items=serialized, count=len(serialized))


@router.post("/from-assessment/{assessment_id}", response_model=ApprovalResponse)
async def create_approval_from_assessment(assessment_id: str, request: Request) -> ApprovalResponse:
    service = _get_execution_service(request)
    try:
        approval = await service.create_approval_from_assessment(assessment_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.args[0]) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await service.sync_positions_with_market()
    return ApprovalResponse.model_validate(_serialize(approval))


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_approval(approval_id: str, request: Request) -> ApprovalResponse:
    service = _get_execution_service(request)
    try:
        approval = await service.approve_and_execute(approval_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.args[0]) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await service.sync_positions_with_market()
    return ApprovalResponse.model_validate(_serialize(approval))


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_approval(
    approval_id: str,
    request: Request,
    payload: RejectApprovalRequest | None = Body(default=None),
) -> ApprovalResponse:
    service = _get_execution_service(request)
    try:
        approval = await service.reject(approval_id, reason=payload.reason if payload is not None else None)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.args[0]) from exc

    await service.sync_positions_with_market()
    return ApprovalResponse.model_validate(_serialize(approval))

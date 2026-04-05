from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.execution import PositionListResponse, PositionResponse

router = APIRouter(prefix="/positions")


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


@router.get("", response_model=PositionListResponse)
async def get_positions(request: Request) -> PositionListResponse:
    service = _get_execution_service(request)
    items = await service.get_positions()
    serialized = [PositionResponse.model_validate(_serialize(item)) for item in items]
    return PositionListResponse(items=serialized, count=len(serialized))


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(position_id: str, request: Request) -> PositionResponse:
    service = _get_execution_service(request)
    position = await service.get_position(position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    return PositionResponse.model_validate(_serialize(position))

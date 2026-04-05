from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.execution import PnlResponse

router = APIRouter(prefix="/pnl")


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


@router.get("", response_model=PnlResponse)
async def get_pnl(request: Request) -> PnlResponse:
    service = _get_execution_service(request)
    summary = await service.get_pnl_summary()
    return PnlResponse.model_validate(_serialize(summary))

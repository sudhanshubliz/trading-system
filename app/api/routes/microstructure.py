from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.microstructure import MicrostructureSnapshotListResponse, MicrostructureSnapshotResponse

router = APIRouter(prefix="/microstructure")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_microstructure_service(request: Request) -> Any:
    service = getattr(request.app.state, "microstructure_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Microstructure service is unavailable")
    return service


@router.get("/current", response_model=MicrostructureSnapshotListResponse)
async def get_current_microstructure(
    request: Request,
    symbol: str | None = Query(default=None),
) -> MicrostructureSnapshotListResponse:
    service = _get_microstructure_service(request)
    items = []
    symbols = [symbol.upper()] if symbol else getattr(service, "supported_symbols", [])
    for item_symbol in symbols:
        snapshot = await service.compute_symbol(item_symbol)
        if snapshot is not None:
            items.append(MicrostructureSnapshotResponse.model_validate(_serialize(snapshot)))
    return MicrostructureSnapshotListResponse(items=items, count=len(items))


@router.get("/history", response_model=MicrostructureSnapshotListResponse)
async def get_microstructure_history(
    request: Request,
    symbol: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1),
) -> MicrostructureSnapshotListResponse:
    service = _get_microstructure_service(request)
    items = service.list_history(symbol=symbol, limit=limit)
    serialized = [MicrostructureSnapshotResponse.model_validate(_serialize(item)) for item in items]
    return MicrostructureSnapshotListResponse(items=serialized, count=len(serialized))

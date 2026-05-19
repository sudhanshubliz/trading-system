from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.regime import RegimeSnapshotListResponse, RegimeSnapshotResponse

router = APIRouter(prefix="/regime")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_regime_service(request: Request) -> Any:
    service = getattr(request.app.state, "regime_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Regime service is unavailable")
    return service


@router.get("/current", response_model=RegimeSnapshotListResponse)
async def get_current_regimes(
    request: Request,
    symbol: str | None = Query(default=None),
) -> RegimeSnapshotListResponse:
    service = _get_regime_service(request)
    symbols = [symbol.upper()] if symbol else getattr(service.feature_service, "supported_symbols", [])
    items = []
    for item_symbol in symbols:
        snapshot = service.get_current(item_symbol)
        if snapshot is not None:
            items.append(RegimeSnapshotResponse.model_validate(_serialize(snapshot)))
    return RegimeSnapshotListResponse(items=items, count=len(items))


@router.get("/history", response_model=RegimeSnapshotListResponse)
async def get_regime_history(
    request: Request,
    symbol: str | None = Query(default=None),
    limit: int | None = Query(default=20, ge=1),
) -> RegimeSnapshotListResponse:
    service = _get_regime_service(request)
    items = service.list_history(symbol=symbol, limit=limit)
    serialized = [RegimeSnapshotResponse.model_validate(_serialize(item)) for item in items]
    return RegimeSnapshotListResponse(items=serialized, count=len(serialized))

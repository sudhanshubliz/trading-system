from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.alpha import (
    AlphaFeatureResponse,
    AlphaSourceReadingListResponse,
    AlphaSourceReadingResponse,
    AlphaFusionEvaluateRequest,
    FusedAlphaSignalListResponse,
    FusedAlphaSignalResponse,
)

router = APIRouter(prefix="/alpha")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_alpha_fusion_service(request: Request) -> Any:
    service = getattr(request.app.state, "alpha_fusion_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alpha fusion service is unavailable",
        )
    return service


@router.get("/features/{symbol}", response_model=AlphaFeatureResponse)
async def get_alpha_features(symbol: str, request: Request) -> AlphaFeatureResponse:
    service = _get_alpha_fusion_service(request)
    snapshot = await service.get_feature_snapshot(symbol)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alpha feature snapshot not available")
    return AlphaFeatureResponse.model_validate(_serialize(snapshot))


@router.get("/fused", response_model=FusedAlphaSignalListResponse)
async def list_fused_alpha(
    request: Request,
    symbol: str | None = Query(default=None),
    limit: int | None = Query(default=20, ge=1),
) -> FusedAlphaSignalListResponse:
    service = _get_alpha_fusion_service(request)
    items = service.list_fused_signals(symbol=symbol, limit=limit)
    serialized = [FusedAlphaSignalResponse.model_validate(_serialize(item)) for item in items]
    return FusedAlphaSignalListResponse(items=serialized, count=len(serialized))


@router.get("/fused/{signal_id}", response_model=FusedAlphaSignalResponse)
async def get_fused_alpha(signal_id: str, request: Request) -> FusedAlphaSignalResponse:
    service = _get_alpha_fusion_service(request)
    item = service.get_fused_signal(signal_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fused opportunity not found")
    return FusedAlphaSignalResponse.model_validate(_serialize(item))


@router.get("/sources", response_model=AlphaSourceReadingListResponse)
async def list_alpha_sources(
    request: Request,
    symbol: str | None = Query(default=None),
    source: str | None = Query(default=None),
    source_name: str | None = Query(default=None),
    limit: int | None = Query(default=50, ge=1),
) -> AlphaSourceReadingListResponse:
    service = _get_alpha_fusion_service(request)
    items = service.list_source_readings(
        symbol_or_market=symbol,
        source_name=source_name or source,
        limit=limit,
    )
    serialized = [AlphaSourceReadingResponse.model_validate(_serialize(item)) for item in items]
    return AlphaSourceReadingListResponse(items=serialized, count=len(serialized))


@router.post("/fused", response_model=FusedAlphaSignalListResponse)
async def evaluate_fused_alpha(
    payload: AlphaFusionEvaluateRequest,
    request: Request,
) -> FusedAlphaSignalListResponse:
    service = _get_alpha_fusion_service(request)
    targets = payload.targets
    if targets is None:
        targets = []
        if payload.symbols:
            targets.extend(payload.symbols)
        if payload.markets:
            targets.extend(payload.markets)
    items = await service.evaluate_targets(targets or payload.symbols)
    serialized = [FusedAlphaSignalResponse.model_validate(_serialize(item)) for item in items]
    return FusedAlphaSignalListResponse(items=serialized, count=len(serialized))

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.features import (
    FeatureCatalogResponse,
    FeatureComputeBatchRequest,
    FeatureComputeRequest,
    FeatureRunListResponse,
    FeatureRunResponse,
)

router = APIRouter(prefix="/features")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_feature_service(request: Request) -> Any:
    service = getattr(request.app.state, "feature_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Feature service is unavailable")
    return service


@router.get("/catalog", response_model=FeatureCatalogResponse)
async def get_catalog(request: Request) -> FeatureCatalogResponse:
    service = _get_feature_service(request)
    items = service.get_catalog()
    return FeatureCatalogResponse(items=[_serialize(item) for item in items], count=len(items))


@router.post("/compute", response_model=FeatureRunResponse)
async def compute_features(payload: FeatureComputeRequest, request: Request) -> FeatureRunResponse:
    service = _get_feature_service(request)
    run = await service.compute_symbol(payload.symbol, persist=True)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature snapshot unavailable")
    return FeatureRunResponse.model_validate(_serialize(run))


@router.post("/compute/batch", response_model=FeatureRunListResponse)
async def compute_features_batch(
    payload: FeatureComputeBatchRequest,
    request: Request,
) -> FeatureRunListResponse:
    service = _get_feature_service(request)
    items = await service.compute_batch(payload.symbols)
    serialized = [FeatureRunResponse.model_validate(_serialize(item)) for item in items]
    return FeatureRunListResponse(items=serialized, count=len(serialized))

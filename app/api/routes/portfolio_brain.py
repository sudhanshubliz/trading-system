from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.portfolio_brain import AllocationRecommendationListResponse, AllocationRecommendationResponse, PortfolioBrainHistoryResponse, PortfolioBrainSnapshotResponse

router = APIRouter(prefix="/portfolio")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    service = getattr(request.app.state, "portfolio_brain_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Portfolio brain service is unavailable")
    return service


@router.get("/brain", response_model=PortfolioBrainSnapshotResponse)
async def get_portfolio_brain(request: Request, execution_mode: str = "paper") -> PortfolioBrainSnapshotResponse:
    service = _get_service(request)
    snapshot = service.generate_recommendations(execution_mode=execution_mode)
    return PortfolioBrainSnapshotResponse.model_validate(_serialize(snapshot))


@router.get("/allocations/recommendations", response_model=AllocationRecommendationListResponse)
async def get_portfolio_allocation_recommendations(request: Request, limit: int = Query(default=50, ge=1)) -> AllocationRecommendationListResponse:
    service = _get_service(request)
    items = service.list_allocations(limit=limit)
    serialized = [AllocationRecommendationResponse.model_validate(_serialize(item)) for item in items]
    return AllocationRecommendationListResponse(items=serialized, count=len(serialized))


@router.get("/allocations/history", response_model=PortfolioBrainHistoryResponse)
async def get_portfolio_allocation_history(request: Request, limit: int = Query(default=50, ge=1)) -> PortfolioBrainHistoryResponse:
    service = _get_service(request)
    items = service.list_history(limit=limit)
    serialized = [PortfolioBrainSnapshotResponse.model_validate(_serialize(item)) for item in items]
    return PortfolioBrainHistoryResponse(items=serialized, count=len(serialized))


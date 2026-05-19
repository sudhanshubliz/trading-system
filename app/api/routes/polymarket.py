from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.polymarket import PolymarketMarketListResponse, PolymarketMarketResponse, PolymarketOpportunityListResponse, PolymarketOpportunityResponse

router = APIRouter(prefix="/polymarket")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    service = getattr(request.app.state, "polymarket_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Polymarket service is unavailable")
    return service


@router.get("/markets", response_model=PolymarketMarketListResponse)
async def list_markets(request: Request) -> PolymarketMarketListResponse:
    service = _get_service(request)
    items = await service.list_markets()
    serialized = [PolymarketMarketResponse.model_validate(_serialize(item)) for item in items]
    return PolymarketMarketListResponse(items=serialized, count=len(serialized))


@router.get("/markets/{market_id}", response_model=PolymarketMarketResponse)
async def get_market(market_id: str, request: Request) -> PolymarketMarketResponse:
    service = _get_service(request)
    item = await service.get_market(market_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Polymarket market not found")
    return PolymarketMarketResponse.model_validate(_serialize(item))


@router.get("/opportunities", response_model=PolymarketOpportunityListResponse)
async def list_opportunities(
    request: Request,
    tradable: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1),
) -> PolymarketOpportunityListResponse:
    service = _get_service(request)
    await service.evaluate_opportunities()
    items = service.list_persisted_opportunities(tradable=tradable, limit=limit)
    serialized = [PolymarketOpportunityResponse.model_validate({**_serialize(item), "id": item.opportunity_id}) for item in items]
    return PolymarketOpportunityListResponse(items=serialized, count=len(serialized))


@router.get("/opportunities/{opportunity_id}", response_model=PolymarketOpportunityResponse)
async def get_opportunity(opportunity_id: str, request: Request) -> PolymarketOpportunityResponse:
    service = _get_service(request)
    item = await service.get_opportunity(opportunity_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Polymarket opportunity not found")
    return PolymarketOpportunityResponse.model_validate({**_serialize(item), "id": item.opportunity_id})


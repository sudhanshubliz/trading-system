from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.arbitrage import ArbitrageOpportunityListResponse, ArbitrageOpportunityResponse

router = APIRouter(prefix="/arbitrage")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_arbitrage_service(request: Request) -> Any:
    service = getattr(request.app.state, "arbitrage_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Arbitrage service is unavailable")
    return service


def _get_polymarket_service(request: Request) -> Any | None:
    return getattr(request.app.state, "polymarket_service", None)


@router.get("/opportunities", response_model=ArbitrageOpportunityListResponse)
async def list_arbitrage_opportunities(
    request: Request,
    symbol: str | None = Query(default=None),
    tradable: bool | None = Query(default=None),
    confidence: float | None = Query(default=None, ge=0.0),
    recency_seconds: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1),
) -> ArbitrageOpportunityListResponse:
    service = _get_arbitrage_service(request)
    basis_items = service.list_opportunities(
        symbol=symbol,
        tradable=tradable,
        min_confidence=confidence,
        recency_seconds=recency_seconds,
        limit=limit,
    )
    polymarket_service = _get_polymarket_service(request)
    polymarket_items = []
    if polymarket_service is not None:
        await polymarket_service.evaluate_opportunities()
        polymarket_items = polymarket_service.list_persisted_opportunities(
            tradable=tradable,
            limit=limit,
        )
        if symbol is not None:
            polymarket_items = [
                item for item in polymarket_items if item.market_id == symbol or symbol.lower() in item.market_title.lower()
            ]
        if confidence is not None:
            polymarket_items = [item for item in polymarket_items if item.confidence >= confidence]
        if recency_seconds is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - recency_seconds
            polymarket_items = [item for item in polymarket_items if item.timestamp.timestamp() >= cutoff]
    combined = sorted(
        [*basis_items, *polymarket_items],
        key=lambda item: item.timestamp,
        reverse=True,
    )[:limit]
    serialized = [
        ArbitrageOpportunityResponse.model_validate({**_serialize(item), "id": item.opportunity_id})
        for item in combined
    ]
    return ArbitrageOpportunityListResponse(items=serialized, count=len(serialized))


@router.get("/opportunities/{opportunity_id}", response_model=ArbitrageOpportunityResponse)
async def get_arbitrage_opportunity(opportunity_id: str, request: Request) -> ArbitrageOpportunityResponse:
    service = _get_arbitrage_service(request)
    item = service.get_opportunity(opportunity_id)
    if item is None:
        polymarket_service = _get_polymarket_service(request)
        if polymarket_service is not None:
            item = await polymarket_service.get_opportunity(opportunity_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arbitrage opportunity not found")
    return ArbitrageOpportunityResponse.model_validate({**_serialize(item), "id": item.opportunity_id})

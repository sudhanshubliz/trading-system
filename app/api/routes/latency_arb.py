from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, Request

from app.schemas.latency_arb import (
    LatencyArbOpportunityListResponse,
    LatencyArbOpportunityResponse,
    LatencyArbSummaryResponse,
)

router = APIRouter(prefix="/latency-arb")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    return getattr(request.app.state, "latency_arb_service", None)


@router.get("/opportunities", response_model=LatencyArbOpportunityListResponse)
async def list_opportunities(request: Request) -> LatencyArbOpportunityListResponse:
    service = _get_service(request)
    items = [] if service is None else service.list_opportunities(limit=100)
    serialized = [LatencyArbOpportunityResponse.model_validate(_serialize(item)) for item in items]
    return LatencyArbOpportunityListResponse(items=serialized, count=len(serialized))


@router.post("/evaluate", response_model=LatencyArbOpportunityListResponse)
async def evaluate_opportunities(request: Request) -> LatencyArbOpportunityListResponse:
    service = _get_service(request)
    items = [] if service is None else await service.evaluate()
    serialized = [LatencyArbOpportunityResponse.model_validate(_serialize(item)) for item in items]
    return LatencyArbOpportunityListResponse(items=serialized, count=len(serialized))


@router.get("/summary", response_model=LatencyArbSummaryResponse)
async def summary(request: Request) -> LatencyArbSummaryResponse:
    service = _get_service(request)
    payload = {"count": 0, "tradable_count": 0, "symbols": [], "top_net_edge_bps": 0.0} if service is None else service.build_summary()
    return LatencyArbSummaryResponse.model_validate(payload)

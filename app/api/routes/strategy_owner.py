from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.strategy_owner import (
    StrategyDecisionCandidateResponse,
    StrategyOwnerCandidateListResponse,
    StrategyOwnerDecisionListResponse,
    StrategyOwnerDecisionResponse,
    StrategyOwnerEvaluateRequest,
    StrategyOwnerEvaluationResponse,
    StrategyOwnerSummaryResponse,
)

router = APIRouter(prefix="/strategy-owner")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    service = getattr(request.app.state, "strategy_owner_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Strategy owner service is unavailable",
        )
    return service


@router.get("/candidates", response_model=StrategyOwnerCandidateListResponse)
async def list_candidates(
    request: Request,
    strategy_family: str | None = Query(default=None),
    source: str | None = Query(default=None),
    symbol_or_market: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1),
) -> StrategyOwnerCandidateListResponse:
    service = _get_service(request)
    items = service.list_candidates(
        strategy_family=strategy_family,
        source_name=source,
        symbol_or_market=symbol_or_market,
        limit=limit,
    )
    serialized = [StrategyDecisionCandidateResponse.model_validate(_serialize(item)) for item in items]
    return StrategyOwnerCandidateListResponse(items=serialized, count=len(serialized))


@router.get("/decisions", response_model=StrategyOwnerDecisionListResponse)
async def list_decisions(
    request: Request,
    status_value: str | None = Query(default=None, alias="status"),
    strategy_family: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1),
) -> StrategyOwnerDecisionListResponse:
    service = _get_service(request)
    items = service.list_decisions(status=status_value, strategy_family=strategy_family, limit=limit)
    serialized = [StrategyOwnerDecisionResponse.model_validate(_serialize(item)) for item in items]
    return StrategyOwnerDecisionListResponse(items=serialized, count=len(serialized))


@router.get("/rejections", response_model=StrategyOwnerDecisionListResponse)
async def list_rejections(
    request: Request,
    limit: int = Query(default=50, ge=1),
) -> StrategyOwnerDecisionListResponse:
    service = _get_service(request)
    items = service.list_rejections(limit=limit)
    serialized = [StrategyOwnerDecisionResponse.model_validate(_serialize(item)) for item in items]
    return StrategyOwnerDecisionListResponse(items=serialized, count=len(serialized))


@router.get("/summary", response_model=StrategyOwnerSummaryResponse)
async def get_summary(request: Request) -> StrategyOwnerSummaryResponse:
    service = _get_service(request)
    return StrategyOwnerSummaryResponse.model_validate(_serialize(service.build_summary()))


@router.post("/evaluate", response_model=StrategyOwnerEvaluationResponse)
async def evaluate(
    payload: StrategyOwnerEvaluateRequest,
    request: Request,
) -> StrategyOwnerEvaluationResponse:
    service = _get_service(request)
    result = await service.evaluate(symbols=payload.symbols, markets=payload.markets)
    return StrategyOwnerEvaluationResponse(
        candidates=[StrategyDecisionCandidateResponse.model_validate(_serialize(item)) for item in result.candidates],
        decisions=[StrategyOwnerDecisionResponse.model_validate(_serialize(item)) for item in result.decisions],
        accepted_count=result.accepted_count,
        rejected_count=result.rejected_count,
        forwarded_to_risk_count=result.forwarded_to_risk_count,
    )

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, Query, Request

from app.schemas.promotion import (
    PromotionBlockersResponse,
    PromotionEvidenceResponse,
    PromotionReviewListResponse,
    PromotionReviewResponse,
    StrategyPromotionStatusListResponse,
    StrategyPromotionStatusResponse,
)

router = APIRouter(prefix="/promotion")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    return request.app.state.promotion_service


@router.get("/status", response_model=StrategyPromotionStatusListResponse)
async def get_promotion_status(request: Request) -> StrategyPromotionStatusListResponse:
    service = _get_service(request)
    items = service.list_status()
    serialized = [StrategyPromotionStatusResponse.model_validate(_serialize(item)) for item in items]
    return StrategyPromotionStatusListResponse(items=serialized, count=len(serialized))


@router.post("/review", response_model=PromotionReviewResponse)
async def review_promotion(request: Request, strategy_name: str = Query(...)) -> PromotionReviewResponse:
    service = _get_service(request)
    review = service.record_review(strategy_name)
    return PromotionReviewResponse.model_validate(_serialize(review))


@router.post("/review/{strategy_family}", response_model=PromotionReviewResponse)
async def review_promotion_strategy(strategy_family: str, request: Request) -> PromotionReviewResponse:
    service = _get_service(request)
    review = service.record_review(strategy_family)
    return PromotionReviewResponse.model_validate(_serialize(review))


@router.get("/ladder", response_model=PromotionReviewListResponse)
async def get_promotion_ladder(request: Request, limit: int = Query(default=50, ge=1)) -> PromotionReviewListResponse:
    service = _get_service(request)
    items = service.list_reviews(limit=limit)
    serialized = [PromotionReviewResponse.model_validate(_serialize(item)) for item in items]
    return PromotionReviewListResponse(items=serialized, count=len(serialized))


@router.get("/blockers/{strategy_family}", response_model=PromotionBlockersResponse)
async def get_promotion_blockers(strategy_family: str, request: Request) -> PromotionBlockersResponse:
    service = _get_service(request)
    payload = service.get_blockers(strategy_family)
    return PromotionBlockersResponse.model_validate(_serialize(payload))


@router.get("/evidence/{strategy_family}", response_model=PromotionEvidenceResponse)
async def get_promotion_evidence(strategy_family: str, request: Request) -> PromotionEvidenceResponse:
    service = _get_service(request)
    payload = _serialize(service.get_evidence(strategy_family))
    return PromotionEvidenceResponse.model_validate(payload)

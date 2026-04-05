from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.portfolio import (
    PortfolioAllocationsResponse,
    PortfolioEvaluateRequest,
    PortfolioEvaluateResponse,
    PortfolioHistoryResponse,
    PortfolioRebalanceResponse,
    PortfolioStatusResponse,
)

router = APIRouter(prefix="/portfolio")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_portfolio_service(request: Request) -> Any:
    service = getattr(request.app.state, "portfolio_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Portfolio service is unavailable",
        )
    return service


@router.get("/status", response_model=PortfolioStatusResponse)
async def get_portfolio_status(request: Request, execution_mode: str = "paper") -> PortfolioStatusResponse:
    service = _get_portfolio_service(request)
    payload = _serialize(service.get_portfolio_state(execution_mode))
    return PortfolioStatusResponse.model_validate(payload)


@router.get("/allocations", response_model=PortfolioAllocationsResponse)
async def get_portfolio_allocations(request: Request, execution_mode: str = "paper") -> PortfolioAllocationsResponse:
    service = _get_portfolio_service(request)
    payload = _serialize(service.get_allocations(execution_mode))
    return PortfolioAllocationsResponse.model_validate(payload)


@router.post("/evaluate", response_model=PortfolioEvaluateResponse)
async def evaluate_portfolio_candidates(
    request_payload: PortfolioEvaluateRequest,
    request: Request,
) -> PortfolioEvaluateResponse:
    service = _get_portfolio_service(request)
    payload = _serialize(
        service.evaluate_candidates(
            request_payload.assessment_ids,
            execution_mode=request_payload.execution_mode,
        )
    )
    return PortfolioEvaluateResponse.model_validate(payload)


@router.post("/rebalance", response_model=PortfolioRebalanceResponse)
async def rebalance_portfolio(request: Request, execution_mode: str = "paper") -> PortfolioRebalanceResponse:
    service = _get_portfolio_service(request)
    payload = _serialize(service.rebalance_portfolio(execution_mode))
    return PortfolioRebalanceResponse.model_validate(payload)


@router.get("/history", response_model=PortfolioHistoryResponse)
async def get_portfolio_history(
    request: Request,
    execution_mode: str | None = None,
    limit: int = 100,
) -> PortfolioHistoryResponse:
    service = _get_portfolio_service(request)
    items = _serialize(service.list_history(execution_mode=execution_mode, limit=limit))
    return PortfolioHistoryResponse(items=items, count=len(items))

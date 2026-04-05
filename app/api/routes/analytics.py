from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.analytics import (
    AttributionSummaryResponse,
    PortfolioAnalyticsResponse,
    RegimeAnalyticsResponse,
    StrategyAttributionResponse,
    SymbolAttributionResponse,
)

router = APIRouter(prefix="/analytics")


def _get_analytics_service(request: Request):
    service = getattr(request.app.state, "analytics_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics service is unavailable",
        )
    return service


@router.get("/portfolio", response_model=PortfolioAnalyticsResponse)
async def get_portfolio_analytics(request: Request, execution_mode: str | None = None) -> PortfolioAnalyticsResponse:
    service = _get_analytics_service(request)
    return PortfolioAnalyticsResponse.model_validate(service.get_portfolio_metrics(execution_mode))


@router.get("/strategy", response_model=StrategyAttributionResponse)
async def get_strategy_analytics(request: Request, execution_mode: str | None = None) -> StrategyAttributionResponse:
    service = _get_analytics_service(request)
    return StrategyAttributionResponse.model_validate(service.get_strategy_attribution(execution_mode))


@router.get("/symbol", response_model=SymbolAttributionResponse)
async def get_symbol_analytics(request: Request, execution_mode: str | None = None) -> SymbolAttributionResponse:
    service = _get_analytics_service(request)
    return SymbolAttributionResponse.model_validate(service.get_symbol_attribution(execution_mode))


@router.get("/regime", response_model=RegimeAnalyticsResponse)
async def get_regime_analytics(request: Request, execution_mode: str | None = None) -> RegimeAnalyticsResponse:
    service = _get_analytics_service(request)
    return RegimeAnalyticsResponse.model_validate(service.get_regime_summary(execution_mode))


@router.get("/attribution", response_model=AttributionSummaryResponse)
async def get_attribution_summary(request: Request, execution_mode: str | None = None) -> AttributionSummaryResponse:
    service = _get_analytics_service(request)
    return AttributionSummaryResponse.model_validate(service.get_attribution_summary(execution_mode))

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.reports import ReportResponse

router = APIRouter(prefix="/reports")


def _get_reporting_service(request: Request):
    service = getattr(request.app.state, "reporting_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Reporting service is unavailable")
    return service


@router.get("/daily", response_model=ReportResponse)
async def get_daily_report(
    request: Request,
    execution_mode: str | None = Query(default=None),
) -> ReportResponse:
    service = _get_reporting_service(request)
    return ReportResponse.model_validate(service.get_daily_report(execution_mode=execution_mode))


@router.get("/weekly", response_model=ReportResponse)
async def get_weekly_report(
    request: Request,
    execution_mode: str | None = Query(default=None),
) -> ReportResponse:
    service = _get_reporting_service(request)
    return ReportResponse.model_validate(service.get_weekly_report(execution_mode=execution_mode))


@router.get("/strategy", response_model=ReportResponse)
async def get_strategy_report(
    request: Request,
    execution_mode: str | None = Query(default=None),
) -> ReportResponse:
    service = _get_reporting_service(request)
    return ReportResponse.model_validate(service.get_strategy_report(execution_mode=execution_mode))


@router.get("/symbol", response_model=ReportResponse)
async def get_symbol_report(
    request: Request,
    execution_mode: str | None = Query(default=None),
) -> ReportResponse:
    service = _get_reporting_service(request)
    return ReportResponse.model_validate(service.get_symbol_report(execution_mode=execution_mode))

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.execution_quality import ExecutionQualityRecordListResponse, ExecutionQualityRecordResponse

router = APIRouter(prefix="/execution")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_execution_quality_service(request: Request) -> Any:
    service = getattr(request.app.state, "execution_quality_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Execution quality service is unavailable",
        )
    return service


@router.get("/quality", response_model=ExecutionQualityRecordListResponse)
async def list_execution_quality(
    request: Request,
    mode: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    strategy_name: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0),
    max_score: float | None = Query(default=None, le=1.0),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1),
) -> ExecutionQualityRecordListResponse:
    service = _get_execution_quality_service(request)
    items = service.list_records(
        mode=mode,
        symbol=symbol,
        strategy_name=strategy_name,
        min_score=min_score,
        max_score=max_score,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    serialized = [ExecutionQualityRecordResponse.model_validate(_serialize(item)) for item in items]
    return ExecutionQualityRecordListResponse(items=serialized, count=len(serialized))


@router.get("/quality/{trade_id}", response_model=ExecutionQualityRecordListResponse)
async def get_execution_quality_for_trade(trade_id: str, request: Request) -> ExecutionQualityRecordListResponse:
    service = _get_execution_quality_service(request)
    items = service.get_records_for_trade(trade_id)
    if not items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution quality records not found")
    serialized = [ExecutionQualityRecordResponse.model_validate(_serialize(item)) for item in items]
    return ExecutionQualityRecordListResponse(items=serialized, count=len(serialized))

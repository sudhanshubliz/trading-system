from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.execution import TradeListResponse, TradeResponse

router = APIRouter(prefix="/trades")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_execution_service(request: Request) -> Any:
    service = getattr(request.app.state, "execution_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Execution service is unavailable",
        )
    return service


@router.get("", response_model=TradeListResponse)
async def get_trades(request: Request) -> TradeListResponse:
    service = _get_execution_service(request)
    items = await service.get_trades()
    serialized = [TradeResponse.model_validate(_serialize(item)) for item in items]
    return TradeListResponse(items=serialized, count=len(serialized))


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(trade_id: str, request: Request) -> TradeResponse:
    service = _get_execution_service(request)
    trade = await service.get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    return TradeResponse.model_validate(_serialize(trade))

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.signals import SignalEvaluateRequest, SignalEvaluateResponse, SignalListResponse, SignalResponse

router = APIRouter(prefix="/signals")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_signal_service(request: Request) -> Any:
    service = getattr(request.app.state, "signal_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Signal service is unavailable",
        )
    return service


@router.get("", response_model=SignalListResponse)
async def get_signals(
    request: Request,
    symbol: str | None = Query(default=None),
    strategy_name: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
) -> SignalListResponse:
    service = _get_signal_service(request)
    items = service.get_signals(symbol=symbol, strategy_name=strategy_name, limit=limit)
    serialized = [SignalResponse.model_validate(_serialize(item)) for item in items]
    return SignalListResponse(items=serialized, count=len(serialized))


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(signal_id: str, request: Request) -> SignalResponse:
    service = _get_signal_service(request)
    signal = service.get_signal(signal_id)
    if signal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found")
    return SignalResponse.model_validate(_serialize(signal))


@router.post("/evaluate", response_model=SignalEvaluateResponse)
async def evaluate_signals(
    payload: SignalEvaluateRequest,
    request: Request,
) -> SignalEvaluateResponse:
    service = _get_signal_service(request)
    items = await service.evaluate_symbols(payload.symbols)
    serialized = [SignalResponse.model_validate(_serialize(item)) for item in items]
    return SignalEvaluateResponse(items=serialized, count=len(serialized))

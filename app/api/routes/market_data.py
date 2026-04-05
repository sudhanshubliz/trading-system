from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.market_data.service import MarketDataService
from app.schemas.market_data import (
    CandleResponse,
    CandleSeriesResponse,
    MarketDataHealthResponse,
    MarketSnapshotListResponse,
    MarketSnapshotResponse,
)

router = APIRouter(prefix="/market-data")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def get_market_data_service(request: Request) -> MarketDataService:
    service = getattr(request.app.state, "market_data_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Market data service is unavailable",
        )
    return service


@router.get("/health", response_model=MarketDataHealthResponse)
async def get_market_data_health(request: Request) -> MarketDataHealthResponse:
    service = get_market_data_service(request)
    payload = await service.get_health()
    return MarketDataHealthResponse.model_validate(_serialize(payload))


@router.get("/snapshots", response_model=MarketSnapshotListResponse)
async def get_market_data_snapshots(request: Request) -> MarketSnapshotListResponse:
    service = get_market_data_service(request)
    snapshots = await service.get_latest_snapshots()
    items = [MarketSnapshotResponse.model_validate(_serialize(item)) for item in snapshots]
    return MarketSnapshotListResponse(items=items)


@router.get("/snapshots/{symbol}", response_model=MarketSnapshotResponse)
async def get_market_data_snapshot(symbol: str, request: Request) -> MarketSnapshotResponse:
    service = get_market_data_service(request)
    if not service.supports_symbol(symbol):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported symbol")

    snapshot = await service.get_snapshot(symbol)
    if snapshot is None or snapshot.snapshot_time is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")

    return MarketSnapshotResponse.model_validate(_serialize(snapshot))


@router.get("/candles/{symbol}/{timeframe}", response_model=CandleSeriesResponse)
async def get_market_data_candles(symbol: str, timeframe: str, request: Request) -> CandleSeriesResponse:
    service = get_market_data_service(request)
    if not service.supports_symbol(symbol):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported symbol")
    if not service.supports_timeframe(timeframe):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported timeframe")

    candles = await service.get_candles(symbol, timeframe)
    if candles is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candle data not found")

    items = [CandleResponse.model_validate(_serialize(item)) for item in candles]
    return CandleSeriesResponse(symbol=symbol.upper(), timeframe=timeframe.lower(), items=items)

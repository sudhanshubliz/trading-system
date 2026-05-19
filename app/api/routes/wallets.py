from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.wallets import WalletObservationListResponse, WalletObservationResponse, WalletProfileListResponse, WalletProfileResponse, WalletSignalListResponse, WalletSignalResponse

router = APIRouter(prefix="/wallets")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    service = getattr(request.app.state, "wallet_intel_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Wallet intelligence service is unavailable")
    return service


@router.get("", response_model=WalletProfileListResponse)
async def list_wallets(request: Request) -> WalletProfileListResponse:
    service = _get_service(request)
    items = await service.list_wallets()
    serialized = [WalletProfileResponse.model_validate(_serialize(item)) for item in items]
    return WalletProfileListResponse(items=serialized, count=len(serialized))


@router.get("/leaderboard", response_model=WalletProfileListResponse)
async def wallet_leaderboard(
    request: Request,
    mode: str = Query(default="recent_quality"),
    limit: int = Query(default=20, ge=1),
) -> WalletProfileListResponse:
    service = _get_service(request)
    items = service.leaderboard(mode=mode, limit=limit)
    serialized = [WalletProfileResponse.model_validate(_serialize(item)) for item in items]
    return WalletProfileListResponse(items=serialized, count=len(serialized))


@router.get("/signals", response_model=WalletSignalListResponse)
async def wallet_signals(request: Request, wallet_id: str | None = Query(default=None), limit: int = Query(default=50, ge=1)) -> WalletSignalListResponse:
    service = _get_service(request)
    items = service.list_signals(wallet_id=wallet_id, limit=limit)
    serialized = [WalletSignalResponse.model_validate(_serialize(item)) for item in items]
    return WalletSignalListResponse(items=serialized, count=len(serialized))


@router.get("/observations", response_model=WalletObservationListResponse)
async def wallet_observations(request: Request, wallet_id: str | None = Query(default=None), limit: int = Query(default=50, ge=1)) -> WalletObservationListResponse:
    service = _get_service(request)
    items = service.list_observations(wallet_id=wallet_id, limit=limit)
    serialized = [WalletObservationResponse.model_validate(_serialize(item)) for item in items]
    return WalletObservationListResponse(items=serialized, count=len(serialized))


@router.get("/{wallet_id}", response_model=WalletProfileResponse)
async def get_wallet(wallet_id: str, request: Request) -> WalletProfileResponse:
    service = _get_service(request)
    item = await service.get_wallet(wallet_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")
    return WalletProfileResponse.model_validate(_serialize(item))

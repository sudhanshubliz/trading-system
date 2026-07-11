from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.mirofish import MiroFishExternalScenarioRequest, MiroFishRunRequest, MiroFishScenarioResponse

router = APIRouter(prefix="/simulation/mirofish")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _get_service(request: Request) -> Any:
    service = getattr(request.app.state, "mirofish_adapter", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="MiroFish adapter is unavailable")
    return service


@router.post("/run", response_model=MiroFishScenarioResponse)
async def run_mirofish(payload: MiroFishRunRequest, request: Request) -> MiroFishScenarioResponse:
    service = _get_service(request)
    item = service.run(symbol_or_market=payload.symbol_or_market, payload=payload.payload)
    return MiroFishScenarioResponse.model_validate(_serialize(item))


@router.post("/ingest", response_model=MiroFishScenarioResponse)
async def ingest_mirofish(
    payload: MiroFishExternalScenarioRequest,
    request: Request,
) -> MiroFishScenarioResponse:
    service = _get_service(request)
    try:
        item = service.ingest_external(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return MiroFishScenarioResponse.model_validate(_serialize(item))


@router.get("/latest", response_model=MiroFishScenarioResponse)
async def get_latest_mirofish(request: Request) -> MiroFishScenarioResponse:
    service = _get_service(request)
    item = service.latest()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No MiroFish runs found")
    return MiroFishScenarioResponse.model_validate(_serialize(item))

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.shadow import ShadowStatusResponse

router = APIRouter(prefix="/shadow")


def _get_shadow_service(request: Request):
    service = getattr(request.app.state, "shadow_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Shadow service is unavailable")
    return service


@router.post("/start", response_model=ShadowStatusResponse)
async def start_shadow(request: Request) -> ShadowStatusResponse:
    service = _get_shadow_service(request)
    return ShadowStatusResponse.model_validate(await service.start_shadow())


@router.post("/stop", response_model=ShadowStatusResponse)
async def stop_shadow(request: Request) -> ShadowStatusResponse:
    service = _get_shadow_service(request)
    return ShadowStatusResponse.model_validate(await service.stop_shadow())


@router.get("/status", response_model=ShadowStatusResponse)
async def get_shadow_status(request: Request) -> ShadowStatusResponse:
    service = _get_shadow_service(request)
    return ShadowStatusResponse.model_validate(service.get_status())

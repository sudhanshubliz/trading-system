from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.system_intelligence import SystemIntelligenceSummaryResponse

router = APIRouter(prefix="/system")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


@router.get("/intelligence/summary", response_model=SystemIntelligenceSummaryResponse)
async def get_system_intelligence_summary(request: Request) -> SystemIntelligenceSummaryResponse:
    service = getattr(request.app.state, "alpha_fusion_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alpha fusion service is unavailable",
        )
    return SystemIntelligenceSummaryResponse.model_validate(_serialize(service.build_intelligence_summary(limit=5)))

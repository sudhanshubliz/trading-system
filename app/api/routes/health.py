from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.db.models import SystemState
from app.db.session import get_db
from app.schemas.health import (
    ComponentStatus,
    HealthResponse,
    LivenessResponse,
    ReadinessCheckResponse,
    ReadinessResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def _load_state(db: Session, key: str) -> dict[str, object] | None:
    state = db.get(SystemState, key)
    if state is None:
        return None

    try:
        payload = json.loads(state.value_json)
    except json.JSONDecodeError:
        logger.warning("invalid system state payload key=%s", key)
        return None

    return payload if isinstance(payload, dict) else None


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request, db: Session = Depends(get_db)) -> HealthResponse:
    timestamp = datetime.now(timezone.utc)
    ops_service = getattr(request.app.state, "ops_service", None)
    startup_report = getattr(request.app.state, "startup_report", None)
    recovery_report = getattr(request.app.state, "recovery_report", None)

    try:
        db.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError:
        logger.exception("database health check failed")
        return HealthResponse(
            status="degraded",
            service=settings.app_name,
            version=settings.app_version,
            mode=settings.trading_mode,
            global_pause=False,
            components=ComponentStatus(
                database="error",
                persistence="error",
                event_store="error",
                startup_checks="error",
                recovery="unknown",
            ),
            alive=True,
            ready=False,
            details={"reason": "database_unavailable"},
            timestamp=timestamp,
        )

    trading_mode_state = _load_state(db, "trading_mode") or {"mode": settings.trading_mode}
    global_pause_state = _load_state(db, "global_pause") or {"paused": False}
    operator_status = await ops_service.get_operator_status() if ops_service is not None else None
    ready = True
    components = ComponentStatus(
        database="ok",
        persistence="ok" if getattr(request.app.state, "persistence_ready", False) else "degraded",
        event_store="ok" if getattr(request.app.state, "persistence_ready", False) else "degraded",
        market_data=getattr(operator_status, "market_data_status", None),
        live_controller="ok" if getattr(request.app.state, "live_controller", None) is not None else "degraded",
        recovery="ok" if getattr(recovery_report, "ok", None) is True else ("degraded" if recovery_report is not None else "unknown"),
        startup_checks=startup_report.status if startup_report is not None else "unknown",
    )
    if startup_report is not None:
        ready = startup_report.ready

    return HealthResponse(
        status="healthy" if ready else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        mode=str(trading_mode_state.get("mode", settings.trading_mode)),
        global_pause=bool(global_pause_state.get("paused", False)),
        components=components,
        alive=True,
        ready=ready,
        details={
            "ops_enabled": bool(getattr(operator_status, "ops_enabled", settings.ops_enabled)),
            "deployment_mode": settings.deployment_mode,
        },
        timestamp=timestamp,
    )


@router.get("/health/livez", response_model=LivenessResponse)
def get_livez() -> LivenessResponse:
    return LivenessResponse(status="ok", alive=True, timestamp=datetime.now(timezone.utc))


@router.get("/health/readyz", response_model=ReadinessResponse)
async def get_readyz(request: Request, response: Response) -> ReadinessResponse:
    startup_service = getattr(request.app.state, "startup_check_service", None)
    if startup_service is None:
        report = getattr(request.app.state, "startup_report", None)
    else:
        report = await startup_service.run_checks(write_probe_event=False)
        request.app.state.startup_report = report
        ops_service = getattr(request.app.state, "ops_service", None)
        if ops_service is not None:
            ops_service.set_startup_report(report)

    if report is None:
        report = type("AnonymousReport", (), {"status": "unknown", "ready": False, "boot_ready": False, "results": [], "timestamp": datetime.now(timezone.utc)})()

    payload = ReadinessResponse(
        status=report.status,
        ready=bool(report.ready),
        boot_ready=bool(report.boot_ready),
        checks=[
            ReadinessCheckResponse(
                name=item.name,
                status=item.status,
                message=item.message,
                critical=item.critical,
                details=item.details,
            )
            for item in report.results
        ],
        timestamp=report.timestamp or datetime.now(timezone.utc),
    )
    if not payload.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload

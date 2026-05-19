from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.config.settings import get_settings

router = APIRouter(prefix="/system")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _build_event(event_type: str, payload: dict[str, Any]) -> str:
    envelope = {
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "payload": _serialize(payload),
    }
    body = json.dumps(envelope, separators=(",", ":"))
    return f"event: {event_type}\ndata: {body}\n\n"


async def _build_snapshot(request: Request) -> dict[str, Any]:
    ops_service = getattr(request.app.state, "ops_service", None)
    live_controller = getattr(request.app.state, "live_controller", None)
    rollout_service = getattr(request.app.state, "rollout_service", None)
    provider_health_service = getattr(request.app.state, "provider_health_service", None)
    incident_service = getattr(request.app.state, "openclaw_bridge", None)
    intelligence_service = getattr(request.app.state, "alpha_fusion_service", None)

    if ops_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ops service is unavailable",
        )

    operator_status = await ops_service.get_operator_status()
    live_status = await live_controller.get_live_status() if live_controller is not None else None
    provider_summary = (
        provider_health_service.build_summary() if provider_health_service is not None else {}
    )
    incidents = incident_service.list_incidents(limit=100) if incident_service is not None else []
    rollout_status = rollout_service.get_capital_status() if rollout_service is not None else {}
    intelligence_summary = (
        intelligence_service.build_intelligence_summary(limit=3)
        if intelligence_service is not None
        else {}
    )

    unresolved_incidents = [
        item for item in incidents if item.get("status", "").lower() != "resolved"
    ]
    return {
        "pending_approvals": operator_status.pending_approvals,
        "active_locks": len(operator_status.active_locks),
        "live_armed": bool(getattr(live_status, "armed", False)),
        "live_can_execute": bool(getattr(live_status, "can_execute", False)),
        "incident_count": len(unresolved_incidents),
        "provider_unhealthy": int(provider_summary.get("unhealthy", 0)),
        "provider_degraded": int(provider_summary.get("degraded", 0)),
        "rollout_phase": str(rollout_status.get("current_phase", "unknown")),
        "market_data_status": operator_status.market_data_status,
        "intelligence_flags": _serialize(intelligence_summary.get("system_flags", {})),
    }


def _diff_events(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if previous is None:
        return [("system_summary", current)]

    events: list[tuple[str, dict[str, Any]]] = []
    if previous["pending_approvals"] != current["pending_approvals"]:
        events.append(("approvals", {"pending_approvals": current["pending_approvals"]}))
    if previous["active_locks"] != current["active_locks"]:
        events.append(
            (
                "risk_locks",
                {
                    "active_locks": current["active_locks"],
                    "market_data_status": current["market_data_status"],
                },
            )
        )
    if (
        previous["live_armed"] != current["live_armed"]
        or previous["live_can_execute"] != current["live_can_execute"]
    ):
        events.append(
            (
                "live_status",
                {
                    "live_armed": current["live_armed"],
                    "live_can_execute": current["live_can_execute"],
                },
            )
        )
    if previous["incident_count"] != current["incident_count"]:
        events.append(("incidents", {"incident_count": current["incident_count"]}))
    if (
        previous["provider_unhealthy"] != current["provider_unhealthy"]
        or previous["provider_degraded"] != current["provider_degraded"]
    ):
        events.append(
            (
                "provider_health",
                {
                    "provider_unhealthy": current["provider_unhealthy"],
                    "provider_degraded": current["provider_degraded"],
                },
            )
        )
    if previous["rollout_phase"] != current["rollout_phase"]:
        events.append(("rollout", {"rollout_phase": current["rollout_phase"]}))
    if previous["intelligence_flags"] != current["intelligence_flags"]:
        events.append(("system_summary", current))
    return events


@router.get("/stream")
async def stream_operator_updates(request: Request) -> StreamingResponse:
    settings = get_settings()
    if not settings.dashboard_stream_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator dashboard stream is disabled",
        )

    async def event_generator():
        previous: dict[str, Any] | None = None
        while True:
            if await request.is_disconnected():
                break
            try:
                current = await _build_snapshot(request)
                for event_type, payload in _diff_events(previous, current):
                    yield _build_event(event_type, payload)
                yield _build_event("heartbeat", {"status": "ok"})
                previous = current
            except Exception as exc:
                yield _build_event(
                    "system_summary",
                    {"stream_error": str(exc), "status": "degraded"},
                )
            await asyncio.sleep(settings.dashboard_stream_interval_sec)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

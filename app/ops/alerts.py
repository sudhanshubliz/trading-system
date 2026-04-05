from __future__ import annotations

from datetime import datetime, timezone

from app.live.types import LiveRiskLock
from app.ops.types import AlertPayload, IncidentSummary, OperatorStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_incident_summary(
    *,
    operator_status: OperatorStatus,
    active_locks: list[LiveRiskLock],
    critical_events: list[dict[str, object]],
) -> IncidentSummary:
    items: list[AlertPayload] = []
    pending_actions: list[str] = []
    timestamp = utc_now()

    for lock in active_locks:
        items.append(
            AlertPayload(
                severity="critical",
                category="live_lock",
                message=f"{lock.lock_type}: {lock.reason}",
                source="live_lock_manager",
                created_at=lock.activated_at,
                metadata={"lock_id": lock.lock_id, **lock.metadata},
            )
        )

    for event in critical_events:
        event_type = str(event.get("event_type", "unknown"))
        event_timestamp = event.get("timestamp")
        if isinstance(event_timestamp, str):
            created_at = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))
        elif isinstance(event_timestamp, datetime):
            created_at = event_timestamp
        else:
            created_at = timestamp
        items.append(
            AlertPayload(
                severity="warning",
                category="event",
                message=event_type,
                source="event_store",
                created_at=created_at,
                metadata={"entity_id": event.get("entity_id"), "trade_id": event.get("trade_id")},
            )
        )

    if operator_status.global_pause:
        pending_actions.append("resume_trading_requires_confirmation")
    if operator_status.live_enabled and not operator_status.live_armed:
        pending_actions.append("live_trading_is_disarmed")
    if operator_status.active_locks:
        pending_actions.append("clear_or_resolve_active_live_locks")
    if operator_status.pending_approvals > 0:
        pending_actions.append("pending_approvals_require_manual_review")
    if operator_status.startup_status not in {"ok", "unknown"}:
        pending_actions.append("review_startup_warnings")

    status = "ok"
    if active_locks:
        status = "critical"
    elif critical_events or pending_actions:
        status = "warning"

    items.sort(key=lambda item: item.created_at, reverse=True)
    return IncidentSummary(
        status=status,
        active_lock_count=len(active_locks),
        critical_event_count=len(critical_events),
        pending_actions=pending_actions,
        items=items,
        timestamp=timestamp,
    )

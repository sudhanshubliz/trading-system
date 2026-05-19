from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from datetime import datetime, timezone

from app.config.settings import Settings, get_settings
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.system_records_repo import SystemRecordsRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class OpenClawEnvelope:
    opportunity_id: str
    created_at: datetime
    strategy_family: str
    summary: str
    supporting_factors: list[str] = field(default_factory=list)
    veto_factors: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


class OpenClawBridge:
    """Safe orchestration adapter. It never becomes the source of trading truth."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repo: SystemRecordsRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = repo
        self.events_repo = events_repo

    def build_envelope(
        self,
        *,
        opportunity_id: str,
        strategy_family: str,
        summary: str,
        supporting_factors: list[str] | None = None,
        veto_factors: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OpenClawEnvelope:
        return OpenClawEnvelope(
            opportunity_id=opportunity_id,
            created_at=utc_now(),
            strategy_family=strategy_family,
            summary=summary,
            supporting_factors=supporting_factors or [],
            veto_factors=veto_factors or [],
            metadata=metadata or {"status": "ready"},
        )

    def create_alert(
        self,
        *,
        opportunity_id: str,
        strategy_family: str,
        summary: str,
        severity: str = "medium",
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload = {
            "alert_id": self._build_id(opportunity_id, "alert"),
            "channel": "openclaw",
            "severity": severity,
            "created_at": utc_now(),
            "opportunity_id": opportunity_id,
            "strategy_family": strategy_family,
            "summary": summary,
            "dry_run": self.settings.openclaw_dry_run,
            "metadata": metadata or {},
        }
        if self.repo is not None:
            self.repo.append_alert(payload)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="openclaw_alert_created",
                entity_id=payload["alert_id"],
                payload={"opportunity_id": opportunity_id, "severity": severity, "dry_run": payload["dry_run"]},
            )
        return payload

    def create_approval_request(self, *, opportunity: object, promotion_status: object | None = None) -> dict[str, object]:
        payload = {
            "request_id": self._build_id(getattr(opportunity, "signal_id", getattr(opportunity, "opportunity_id", "unknown")), "approval"),
            "opportunity_id": getattr(opportunity, "signal_id", getattr(opportunity, "opportunity_id", "unknown")),
            "tradable": bool(getattr(opportunity, "metadata", {}).get("tradable", True)) if hasattr(opportunity, "metadata") else True,
            "direction": getattr(opportunity, "direction", getattr(opportunity, "recommended_direction", "neutral")),
            "strategy_family": getattr(opportunity, "strategy_family", "unknown"),
            "promotion_stage": getattr(promotion_status, "current_stage", "research") if promotion_status is not None else "research",
            "requires_human_approval": True,
            "dry_run": self.settings.openclaw_dry_run,
        }
        return payload

    def add_operator_note(
        self,
        *,
        related_entity_id: str | None,
        note: str,
        note_type: str = "operator",
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload = {
            "note_id": self._build_id(related_entity_id or "system", "note"),
            "note_type": note_type,
            "related_entity_id": related_entity_id,
            "created_at": utc_now(),
            "note": note,
            "metadata": metadata or {},
        }
        if self.repo is not None:
            self.repo.append_operator_note(payload)
        return payload

    def create_incident(
        self,
        *,
        category: str,
        severity: str,
        source: str,
        impacted_scope: str,
        title: str,
        summary: str | None = None,
        details: str | None = None,
        related_entity_id: str | None = None,
        related_provider: str | None = None,
        related_strategy: str | None = None,
        related_symbol_or_market: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload = {
            "incident_id": self._build_id(title, "incident"),
            "category": category,
            "severity": severity,
            "source": source,
            "status": "open",
            "impacted_scope": impacted_scope,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "title": title,
            "summary": summary,
            "details": details,
            "related_entity_id": related_entity_id,
            "related_provider": related_provider,
            "related_strategy": related_strategy,
            "related_symbol_or_market": related_symbol_or_market,
            "metadata": metadata or {},
        }
        if self.repo is not None:
            self.repo.append_incident(payload)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="incident_detected",
                entity_id=payload["incident_id"],
                payload={"title": title, "severity": severity, "category": category},
            )
        return payload

    def log_incident(self, *, severity: str, title: str, related_entity_id: str | None = None) -> dict[str, object]:
        return self.create_incident(
            category="external_dependency_failure",
            severity=severity,
            source="openclaw_bridge",
            impacted_scope="system",
            title=title,
            related_entity_id=related_entity_id,
        )

    def get_incident(self, incident_id: str) -> dict[str, object] | None:
        return self.repo.get_incident(incident_id) if self.repo is not None else None

    def acknowledge_incident(self, incident_id: str, *, note: str | None = None, severity: str | None = None) -> dict[str, object] | None:
        incident = self.repo.get_incident(incident_id) if self.repo is not None else None
        if incident is None:
            return None
        payload = {
            "status": "acknowledged",
            "acknowledged_at": utc_now(),
            "updated_at": utc_now(),
        }
        if severity is not None:
            payload["severity"] = severity
        if self.repo is not None:
            incident = self.repo.update_incident(incident_id, payload)
        if note:
            self.add_operator_note(related_entity_id=incident_id, note=note, note_type="incident_ack")
        return incident

    def resolve_incident(self, incident_id: str, *, note: str | None = None) -> dict[str, object] | None:
        incident = self.repo.get_incident(incident_id) if self.repo is not None else None
        if incident is None:
            return None
        if self.repo is not None:
            incident = self.repo.update_incident(
                incident_id,
                {
                    "status": "resolved",
                    "resolved_at": utc_now(),
                    "updated_at": utc_now(),
                },
            )
        if note:
            self.add_operator_note(related_entity_id=incident_id, note=note, note_type="incident_resolve")
        return incident

    def list_operator_notes(self, *, limit: int = 100) -> list[dict[str, object]]:
        return self.repo.list_operator_notes(limit=limit) if self.repo is not None else []

    def list_incidents(self, *, limit: int = 100) -> list[dict[str, object]]:
        return self.repo.list_incidents(limit=limit) if self.repo is not None else []

    def list_alert_history(self, *, limit: int = 100) -> list[dict[str, object]]:
        return self.repo.list_alerts(limit=limit) if self.repo is not None else []

    def health_check(self) -> dict[str, object]:
        if not self.settings.enable_openclaw_bridge:
            return {
                "status": "degraded",
                "success_rate": 0.0,
                "stale_data_flag": True,
                "error_count": 0,
                "notes": ["openclaw_bridge_disabled"],
            }
        return {
            "status": "healthy",
            "success_rate": 1.0,
            "stale_data_flag": False,
            "error_count": 0,
            "notes": ["dry_run" if self.settings.openclaw_dry_run else "live_bridge_configured"],
        }

    def _build_id(self, value: str, kind: str) -> str:
        digest = hashlib.sha1(f"{kind}|{value}|{utc_now().isoformat()}".encode("utf-8")).hexdigest()
        return f"ocl_{digest[:12]}"

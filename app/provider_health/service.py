from __future__ import annotations

import hashlib
import inspect
from collections import OrderedDict
from datetime import datetime, timezone

from app.config.settings import Settings, get_settings
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.provider_health_repo import ProviderHealthRepository
from app.provider_health.types import ProviderHealthSnapshot, ProviderIngestRun


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderHealthService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repo: ProviderHealthRepository | None = None,
        events_repo: EventsRepository | None = None,
        incident_handler: object | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = repo
        self.events_repo = events_repo
        self.incident_handler = incident_handler
        self._latest: OrderedDict[str, ProviderHealthSnapshot] = OrderedDict()

    async def evaluate_provider(self, provider_name: str, provider: object) -> ProviderHealthSnapshot:
        started_at = utc_now()
        notes: list[str] = []
        try:
            health_check = getattr(provider, "health_check", None)
            if health_check is None:
                raise RuntimeError("health_check_not_supported")
            result = health_check()
            if inspect.isawaitable(result):
                result = await result
            payload = result if isinstance(result, dict) else {"status": "healthy"}
            status = str(payload.get("status", "healthy"))
            success_rate = float(payload.get("success_rate", 1.0))
            stale = bool(payload.get("stale_data_flag", False))
            error_count = int(payload.get("error_count", 0))
            last_success_at = payload.get("last_success_at", started_at)
            last_failure_at = payload.get("last_failure_at")
            latency_ms = float(payload.get("latency_ms", max((utc_now() - started_at).total_seconds() * 1000.0, 0.0)))
            notes = list(payload.get("notes", []))
            metadata = dict(payload.get("metadata", {}))
        except Exception as exc:
            status = "unhealthy"
            success_rate = 0.0
            stale = True
            error_count = 1
            last_success_at = None
            last_failure_at = utc_now()
            latency_ms = max((utc_now() - started_at).total_seconds() * 1000.0, 0.0)
            notes = [str(exc)]
            metadata = {}
        status = self._normalize_status(status=status, success_rate=success_rate, stale=stale, error_count=error_count)
        snapshot = ProviderHealthSnapshot(
            snapshot_id=self._build_id(provider_name, started_at),
            provider_name=provider_name,
            status=status,
            latency_ms=round(latency_ms, 6) if latency_ms is not None else None,
            success_rate=round(success_rate, 6),
            stale_data_flag=stale,
            error_count=error_count,
            last_success_at=last_success_at,
            last_failure_at=last_failure_at,
            observed_at=started_at,
            notes=notes,
            metadata=metadata,
        )
        self._store(snapshot)
        if (
            self.settings.incident_auto_create_provider_failure
            and self.incident_handler is not None
            and snapshot.status == "unhealthy"
            and hasattr(self.incident_handler, "create_incident")
        ):
            self.incident_handler.create_incident(
                category="provider_outage",
                severity="high",
                source="provider_health",
                impacted_scope="provider",
                title=f"Provider unhealthy: {provider_name}",
                summary=f"{provider_name} health check entered unhealthy state.",
                details="Automatic provider-health escalation.",
                related_provider=provider_name,
                metadata={"snapshot_id": snapshot.snapshot_id, "notes": snapshot.notes},
            )
        return snapshot

    async def evaluate_all(self, providers: dict[str, object]) -> list[ProviderHealthSnapshot]:
        items: list[ProviderHealthSnapshot] = []
        for provider_name, provider in providers.items():
            items.append(await self.evaluate_provider(provider_name, provider))
        return items

    def get_provider(self, provider_name: str) -> ProviderHealthSnapshot | None:
        if provider_name in self._latest:
            return self._latest[provider_name]
        if self.repo is not None:
            return self.repo.get_latest(provider_name)
        return None

    def list_latest(self) -> list[ProviderHealthSnapshot]:
        if self._latest:
            return list(self._latest.values())
        if self.repo is not None:
            return self.repo.list_latest()
        return []

    def list_events(self, *, provider_name: str | None = None, limit: int = 100) -> list[ProviderHealthSnapshot]:
        if self.repo is not None:
            return self.repo.list_events(provider_name=provider_name, limit=limit)
        items = list(self._latest.values())
        if provider_name is not None:
            items = [item for item in items if item.provider_name == provider_name]
        return items[:limit]

    def record_ingest_run(self, item: ProviderIngestRun) -> ProviderIngestRun:
        if self.repo is not None:
            self.repo.upsert_ingest_run(item)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="provider_ingest_run",
                entity_id=item.run_id,
                payload={
                    "provider_name": item.provider_name,
                    "dataset_type": item.dataset_type,
                    "status": item.status,
                    "records_written": item.records_written,
                },
            )
        return item

    def list_ingest_runs(self, *, provider_name: str | None = None, limit: int = 100) -> list[ProviderIngestRun]:
        if self.repo is not None:
            return self.repo.list_ingest_runs(provider_name=provider_name, limit=limit)
        return []

    def build_summary(self) -> dict[str, object]:
        items = self.list_latest()
        ingest_runs = self.list_ingest_runs(limit=25)
        return {
            "items": [snapshot for snapshot in items],
            "count": len(items),
            "healthy": len([item for item in items if item.status == "healthy"]),
            "degraded": len([item for item in items if item.status == "degraded"]),
            "unhealthy": len([item for item in items if item.status == "unhealthy"]),
            "recent_ingest_runs": ingest_runs,
        }

    def any_unhealthy(self, names: list[str] | None = None) -> bool:
        items = self.list_latest()
        if names is not None:
            names_set = set(names)
            items = [item for item in items if item.provider_name in names_set]
        return any(item.status == "unhealthy" for item in items)

    def _normalize_status(self, *, status: str, success_rate: float, stale: bool, error_count: int) -> str:
        if not self.settings.enable_provider_health:
            return status
        if status == "unhealthy" or error_count >= self.settings.provider_health_unhealthy_threshold:
            return "unhealthy"
        if status == "degraded" or stale or success_rate < self.settings.provider_health_degrade_threshold:
            return "degraded"
        return "healthy"

    def _store(self, snapshot: ProviderHealthSnapshot) -> None:
        self._latest[snapshot.provider_name] = snapshot
        self._latest.move_to_end(snapshot.provider_name, last=False)
        while len(self._latest) > 64:
            self._latest.popitem(last=True)
        if self.repo is not None:
            self.repo.upsert_snapshot(snapshot)
            self.repo.append_event(snapshot)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="provider_health_snapshot",
                entity_id=snapshot.snapshot_id,
                payload={"provider_name": snapshot.provider_name, "status": snapshot.status},
            )

    def _build_id(self, provider_name: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{provider_name}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"phs_{digest[:12]}"

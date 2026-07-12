from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config.settings import Settings, get_settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MiroFishRemoteError(RuntimeError):
    """Raised when the configured upstream MiroFish service cannot be trusted."""


@dataclass(frozen=True, slots=True)
class MiroFishRemoteSimulation:
    simulation_id: str
    status: str
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class MiroFishRemoteReport:
    report_id: str
    simulation_id: str
    status: str
    created_at: str | None
    completed_at: str | None


class MiroFishRemoteClient:
    """Narrow client for a separately deployed 666ghj/MiroFish backend."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.base_url = _validated_base_url(self.settings.mirofish_base_url)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(max(self.settings.mirofish_timeout_ms, 100) / 1000.0),
            verify=self.settings.mirofish_verify_tls,
            follow_redirects=False,
            headers=self._headers(),
        )
        self._success_count = 0
        self._error_count = 0
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._last_latency_ms: float | None = None
        self._last_error: str | None = None

    async def get_simulation(self, simulation_id: str) -> MiroFishRemoteSimulation:
        data = await self._get_wrapped(f"/api/simulation/{_safe_identifier(simulation_id)}")
        remote_id = str(data.get("simulation_id") or "").strip()
        status = str(data.get("status") or "").strip().lower()
        if remote_id != simulation_id or not status:
            raise MiroFishRemoteError("mirofish_invalid_simulation_response")
        return MiroFishRemoteSimulation(
            simulation_id=remote_id,
            status=status,
            updated_at=_optional_string(data.get("updated_at")),
        )

    async def get_report_by_simulation(self, simulation_id: str) -> MiroFishRemoteReport:
        data = await self._get_wrapped(f"/api/report/by-simulation/{_safe_identifier(simulation_id)}")
        report_id = str(data.get("report_id") or "").strip()
        remote_simulation_id = str(data.get("simulation_id") or "").strip()
        status = str(data.get("status") or "").strip().lower()
        if not report_id or remote_simulation_id != simulation_id or not status:
            raise MiroFishRemoteError("mirofish_invalid_report_response")
        return MiroFishRemoteReport(
            report_id=report_id,
            simulation_id=remote_simulation_id,
            status=status,
            created_at=_optional_string(data.get("created_at")),
            completed_at=_optional_string(data.get("completed_at")),
        )

    async def health_check(self) -> dict[str, object]:
        started = monotonic()
        try:
            response = await self._client.get("/health")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or str(payload.get("status") or "").lower() != "ok":
                raise MiroFishRemoteError("mirofish_invalid_health_response")
            self._record_success(started)
            return self._health_payload(status="healthy", stale=False)
        except Exception as exc:
            self._record_failure(started, exc)
            return self._health_payload(status="unhealthy", stale=True)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_wrapped(self, path: str) -> dict[str, Any]:
        started = monotonic()
        try:
            response = await self._client.get(path)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise MiroFishRemoteError("mirofish_invalid_api_envelope")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise MiroFishRemoteError("mirofish_missing_api_data")
            self._record_success(started)
            return data
        except MiroFishRemoteError as exc:
            self._record_failure(started, exc)
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self._record_failure(started, exc)
            raise MiroFishRemoteError("mirofish_upstream_request_failed") from exc

    def _headers(self) -> dict[str, str]:
        token = self.settings.mirofish_auth_token
        if token is None:
            return {}
        value = token.get_secret_value().strip()
        return {"Authorization": f"Bearer {value}"} if value else {}

    def _record_success(self, started: float) -> None:
        self._success_count += 1
        self._error_count = 0
        self._last_success_at = utc_now()
        self._last_latency_ms = max((monotonic() - started) * 1000.0, 0.0)
        self._last_error = None

    def _record_failure(self, started: float, exc: BaseException) -> None:
        self._error_count += 1
        self._last_failure_at = utc_now()
        self._last_latency_ms = max((monotonic() - started) * 1000.0, 0.0)
        self._last_error = type(exc).__name__

    def _health_payload(self, *, status: str, stale: bool) -> dict[str, object]:
        attempts = self._error_count + self._success_count
        success_rate = 0.0 if attempts == 0 else self._success_count / attempts
        return {
            "status": status,
            "latency_ms": self._last_latency_ms,
            "success_rate": success_rate,
            "stale_data_flag": stale,
            "error_count": self._error_count,
            "last_success_at": self._last_success_at,
            "last_failure_at": self._last_failure_at,
            "notes": [self._last_error] if self._last_error else [],
            "metadata": {
                "provider": "666ghj_mirofish",
                "base_url": self.base_url,
                "advisory_only": True,
            },
        }


def _validated_base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid_mirofish_base_url")
    if parsed.query or parsed.fragment:
        raise ValueError("invalid_mirofish_base_url")
    return candidate


def _safe_identifier(value: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > 128 or not all(char.isalnum() or char in {"-", "_"} for char in candidate):
        raise ValueError("invalid_mirofish_identifier")
    return candidate


def _optional_string(value: object) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None

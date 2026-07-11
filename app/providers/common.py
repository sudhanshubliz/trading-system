from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

from app.config.settings import Settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d %H:%M:%S%z"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return None


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def local_fallback_allowed(settings: Settings) -> bool:
    return settings.app_env in {"development", "test"} or settings.deployment_mode == "local"


@dataclass(slots=True)
class ProviderRuntimeState:
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    error_count: int = 0
    last_latency_ms: float | None = None
    last_error_type: str | None = None

    @property
    def has_successful_fetch(self) -> bool:
        return self.last_success_at is not None

    def record_success(self, *, started_at: datetime) -> None:
        self.last_success_at = utc_now()
        self.last_latency_ms = max((utc_now() - started_at).total_seconds() * 1000.0, 0.0)
        self.last_error_type = None

    def record_failure(self, error: BaseException | None = None) -> None:
        self.error_count += 1
        self.last_failure_at = utc_now()
        self.last_error_type = type(error).__name__ if error is not None else "unknown_error"

    def build_health(
        self,
        *,
        max_data_age_seconds: int,
        unhealthy_error_threshold: int = 3,
        metadata: dict[str, object] | None = None,
        degraded_when_unconfigured: bool = True,
        configured: bool = True,
    ) -> dict[str, object]:
        stale = (
            self.last_success_at is None
            or (utc_now() - self.last_success_at).total_seconds() > max(max_data_age_seconds, 1)
        )
        status = "healthy" if self.last_success_at is not None else "degraded"
        if stale and self.last_success_at is not None:
            status = "degraded"
        if not configured and degraded_when_unconfigured:
            status = "degraded"
        if self.error_count >= unhealthy_error_threshold:
            status = "unhealthy"
        return {
            "status": status,
            "latency_ms": self.last_latency_ms,
            "success_rate": 0.0 if self.last_success_at is None and self.error_count else 1.0 if self.error_count == 0 else 0.5,
            "stale_data_flag": stale,
            "error_count": self.error_count,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "notes": [self.last_error_type] if self.last_error_type else [],
            "metadata": metadata or {},
        }


class ExistingAsyncClientContext:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FallbackProviderAdapter:
    def __init__(
        self,
        *,
        real: object,
        mock: object,
        allow_mock_fallback: bool,
        empty_fallback_methods: Iterable[str] = (),
    ) -> None:
        self.real = real
        self.mock = mock
        self.allow_mock_fallback = allow_mock_fallback
        self.empty_fallback_methods = set(empty_fallback_methods)
        self._fallback_active = False

    async def call(self, method_name: str, *args: object):
        try:
            value = await getattr(self.real, method_name)(*args)
            if self._should_fallback_on_empty(method_name=method_name, value=value):
                self._fallback_active = True
                return await getattr(self.mock, method_name)(*args)
            self._fallback_active = False
            return value
        except Exception:
            if not self.allow_mock_fallback:
                raise
            self._fallback_active = True
            return await getattr(self.mock, method_name)(*args)

    async def health_check(self) -> dict[str, object]:
        payload = await getattr(self.real, "health_check")()
        if not isinstance(payload, dict):
            payload = {"status": "degraded"}
        payload.setdefault("metadata", {})
        payload["metadata"]["fallback_active"] = self._fallback_active
        if self._fallback_active and payload.get("status") == "healthy":
            payload["status"] = "degraded"
        return payload

    def _should_fallback_on_empty(self, *, method_name: str, value: object) -> bool:
        if not self.allow_mock_fallback:
            return False
        if value not in (None, [], {}):
            return False
        if method_name not in self.empty_fallback_methods:
            return False
        if hasattr(self.real, "should_fallback_on_empty") and callable(getattr(self.real, "should_fallback_on_empty")):
            return bool(getattr(self.real, "should_fallback_on_empty")(method_name, value))
        return False

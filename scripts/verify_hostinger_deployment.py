from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(slots=True)
class VerificationReport:
    base_url: str
    checks: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def request_json(base_url: str, path: str, *, method: str = "GET", timeout: float = 10.0) -> dict[str, Any]:
    request = Request(f"{base_url.rstrip('/')}/api/v1{path}", method=method)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied deployment endpoint
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"request_failed:{path}:{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid_response:{path}")
    return payload


def verify_deployment(base_url: str, *, start_shadow: bool = False, timeout: float = 10.0) -> VerificationReport:
    report = VerificationReport(base_url=base_url.rstrip("/"))
    try:
        health = request_json(report.base_url, "/health", timeout=timeout)
        ready = request_json(report.base_url, "/health/readyz", timeout=timeout)
        live = request_json(report.base_url, "/live/status", timeout=timeout)
        mirofish = request_json(report.base_url, "/simulation/mirofish/health", timeout=timeout)
        providers = request_json(report.base_url, "/provider-health/summary", timeout=timeout)
        shadow = request_json(report.base_url, "/shadow/status", timeout=timeout)
        if start_shadow and not bool(shadow.get("running")):
            shadow = request_json(report.base_url, "/shadow/start", method="POST", timeout=timeout)
    except RuntimeError as exc:
        report.errors.append(str(exc))
        return report

    _check(report, "backend", health.get("status") == "healthy" and health.get("ready") is True)
    _check(report, "paper_mode", health.get("mode") == "paper")
    _check(report, "readiness", ready.get("ready") is True and ready.get("boot_ready") is True)
    _check(
        report,
        "live_locked",
        live.get("enabled") is False and live.get("armed") is False and live.get("can_execute") is False,
    )

    mirofish_metadata = _mapping(mirofish.get("metadata"))
    upstream = _mapping(mirofish_metadata.get("upstream"))
    _check(report, "mirofish_not_mock", mirofish_metadata.get("source_is_mock") is False)
    _check(report, "mirofish_external_mode", mirofish_metadata.get("provider") in {"external", "real"})
    _check(report, "mirofish_upstream", upstream.get("provider") == "666ghj_mirofish")
    _check(report, "mirofish_available", mirofish.get("status") in {"healthy", "degraded"})
    _check(report, "provider_health", int(providers.get("unhealthy") or 0) == 0)
    _check(report, "shadow_running", shadow.get("running") is True)

    report.details = {
        "backend_status": health.get("status"),
        "execution_mode": health.get("mode"),
        "live_enabled": live.get("enabled"),
        "live_armed": live.get("armed"),
        "live_can_execute": live.get("can_execute"),
        "mirofish_status": mirofish.get("status"),
        "mirofish_notes": mirofish.get("notes", []),
        "provider_unhealthy_count": providers.get("unhealthy"),
        "shadow_running": shadow.get("running"),
        "shadow_cycle_count": shadow.get("cycle_count"),
    }
    return report


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _check(report: VerificationReport, name: str, condition: bool) -> None:
    report.checks[name] = "passed" if condition else "failed"
    if not condition:
        report.errors.append(name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a paper-only Hostinger trading-system deployment.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--start-shadow", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    report = verify_deployment(args.base_url, start_shadow=args.start_shadow, timeout=args.timeout)
    print(
        json.dumps(
            {
                "status": "passed" if report.ok else "failed",
                "base_url": report.base_url,
                "checks": report.checks,
                "errors": report.errors,
                "details": report.details,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

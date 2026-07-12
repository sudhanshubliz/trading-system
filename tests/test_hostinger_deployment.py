from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts import verify_hostinger_deployment as verifier


REPO_ROOT = Path(__file__).resolve().parents[1]


def _responses() -> dict[str, dict[str, Any]]:
    return {
        "/health": {"status": "healthy", "ready": True, "mode": "paper"},
        "/health/readyz": {"ready": True, "boot_ready": True},
        "/live/status": {"enabled": False, "armed": False, "can_execute": False},
        "/simulation/mirofish/health": {
            "status": "degraded",
            "notes": ["no_fresh_validated_scenario"],
            "metadata": {
                "provider": "external",
                "source_is_mock": False,
                "upstream": {"provider": "666ghj_mirofish"},
            },
        },
        "/provider-health/summary": {"unhealthy": 0},
        "/shadow/status": {"running": True, "cycle_count": 3},
    }


def test_hostinger_verifier_accepts_safe_external_advisory_deployment(monkeypatch) -> None:
    responses = _responses()
    monkeypatch.setattr(verifier, "request_json", lambda _base, path, **_kwargs: responses[path])

    report = verifier.verify_deployment("http://127.0.0.1:8000")

    assert report.ok is True
    assert report.checks["live_locked"] == "passed"
    assert report.checks["mirofish_upstream"] == "passed"


def test_hostinger_verifier_fails_if_live_controls_are_enabled(monkeypatch) -> None:
    responses = _responses()
    responses["/live/status"] = {"enabled": True, "armed": False, "can_execute": False}
    monkeypatch.setattr(verifier, "request_json", lambda _base, path, **_kwargs: responses[path])

    report = verifier.verify_deployment("http://127.0.0.1:8000")

    assert report.ok is False
    assert "live_locked" in report.errors


def test_hostinger_verifier_fails_if_mirofish_upstream_is_unhealthy(monkeypatch) -> None:
    responses = _responses()
    responses["/simulation/mirofish/health"]["status"] = "unhealthy"
    responses["/provider-health/summary"]["unhealthy"] = 1
    monkeypatch.setattr(verifier, "request_json", lambda _base, path, **_kwargs: responses[path])

    report = verifier.verify_deployment("http://127.0.0.1:8000")

    assert report.ok is False
    assert "mirofish_available" in report.errors
    assert "provider_health" in report.errors


def test_hostinger_compose_selects_upstream_amd64_image_explicitly() -> None:
    compose = (REPO_ROOT / "deploy" / "docker-compose.hostinger.yml").read_text(encoding="utf-8")

    assert "platform: ${MIROFISH_PLATFORM:-linux/amd64}" in compose
    assert '"127.0.0.1:${TRADING_API_PORT:-8000}:8000"' in compose
    assert "condition: service_completed_successfully" in compose
    assert "scripts/validate_hostinger_environment.py" in compose

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.health import router as health_router
from app.config.settings import get_settings
from app.ops.startup_checks import StartupCheckService


def test_livez_returns_ok_when_process_healthy() -> None:
    app = FastAPI()
    app.include_router(health_router, prefix="/api/v1")

    with TestClient(app) as client:
        response = client.get("/api/v1/health/livez")

    assert response.status_code == 200
    assert response.json()["alive"] is True


def test_readyz_fails_when_required_persistence_unavailable() -> None:
    settings = get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "require_persistence_for_boot": True,
            "readiness_requires_persistence": True,
        }
    )
    app = FastAPI()
    app.include_router(health_router, prefix="/api/v1")
    app.state.startup_check_service = StartupCheckService(
        settings=settings,
        persistence_session_factory=None,
        persistence_available=False,
        persistence_error="persistence_unavailable",
    )
    app.state.startup_report = None
    app.state.ops_service = None
    app.state.persistence_ready = False

    with TestClient(app) as client:
        response = client.get("/api/v1/health/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["ready"] is False
    assert any(item["name"] == "persistence" and item["status"] == "failed" for item in payload["checks"])

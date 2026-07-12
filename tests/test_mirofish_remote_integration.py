from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.mirofish import router as mirofish_router
from app.config.settings import Settings
from app.simulation.mirofish_adapter import MiroFishAdapter
from app.simulation.mirofish_client import MiroFishRemoteClient


def _settings(**updates: object) -> Settings:
    defaults: dict[str, object] = {
        "enable_mirofish": True,
        "mirofish_provider": "external",
        "mirofish_base_url": "https://mirofish.test",
        "mirofish_timeout_ms": 500,
        "mirofish_max_data_age_seconds": 60,
        "mirofish_max_scenario_confidence": 0.4,
    }
    defaults.update(updates)
    return Settings(_env_file=None).model_copy(update=defaults)


def _transport(*, report_status: str = "completed") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "service": "MiroFish Backend"})
        if request.url.path == "/api/simulation/sim_123":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "simulation_id": "sim_123",
                        "status": "completed",
                        "updated_at": "2026-07-11T18:00:00",
                    },
                },
            )
        if request.url.path == "/api/report/by-simulation/sim_123":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "report_id": "report_123",
                        "simulation_id": "sim_123",
                        "status": report_status,
                        "created_at": "2026-07-11T17:00:00",
                        "completed_at": "2026-07-11T18:00:00",
                        "markdown_content": "This text must not become a trading signal.",
                    },
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _adapter(*, report_status: str = "completed") -> tuple[MiroFishAdapter, httpx.AsyncClient]:
    settings = _settings()
    http_client = httpx.AsyncClient(base_url=settings.mirofish_base_url, transport=_transport(report_status=report_status))
    remote = MiroFishRemoteClient(settings=settings, client=http_client)
    return MiroFishAdapter(settings=settings, remote_client=remote), http_client


def _sync_payload() -> dict[str, object]:
    return {
        "simulation_id": "sim_123",
        "scenario_id": "scenario_123",
        "symbol_or_market": "BTCUSDT",
        "simulation_timestamp": datetime.now(timezone.utc),
        "direction_bias": "long",
        "expected_crowd_bias": 0.6,
        "expected_volatility_shift": 0.2,
        "scenario_confidence": 0.9,
        "explanation": "Operator-normalized structured scenario.",
    }


def test_remote_client_normalizes_upstream_contract_and_health() -> None:
    async def run() -> None:
        adapter, client = _adapter()
        assert adapter.remote_client is not None
        health = await adapter.remote_client.health_check()
        simulation = await adapter.remote_client.get_simulation("sim_123")
        report = await adapter.remote_client.get_report_by_simulation("sim_123")
        await client.aclose()

        assert health["status"] == "healthy"
        assert simulation.status == "completed"
        assert report.report_id == "report_123"
        assert report.status == "completed"

    asyncio.run(run())


def test_remote_sync_is_report_backed_capped_and_advisory_only() -> None:
    async def run() -> None:
        adapter, client = _adapter()
        summary = await adapter.sync_remote(_sync_payload())
        source = adapter.as_source_reading(summary)
        await client.aclose()

        assert summary.scenario_confidence == 0.4
        assert summary.advisory_only is True
        assert summary.metadata["upstream_provider"] == "666ghj_mirofish"
        assert summary.metadata["upstream_report_id"] == "report_123"
        assert summary.metadata["report_text_used_as_signal"] is False
        assert source.metadata["advisory_only"] is True
        assert source.metadata["independent_signal"] is False

    asyncio.run(run())


def test_remote_sync_rejects_incomplete_report() -> None:
    async def run() -> None:
        adapter, client = _adapter(report_status="generating")
        with pytest.raises(ValueError, match="mirofish_report_not_completed"):
            await adapter.sync_remote(_sync_payload())
        await client.aclose()

    asyncio.run(run())


def test_remote_health_degrades_safely_when_upstream_is_unavailable() -> None:
    async def run() -> None:
        settings = _settings()

        def unavailable(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline")

        http_client = httpx.AsyncClient(
            base_url=settings.mirofish_base_url,
            transport=httpx.MockTransport(unavailable),
        )
        adapter = MiroFishAdapter(
            settings=settings,
            remote_client=MiroFishRemoteClient(settings=settings, client=http_client),
        )
        health = await adapter.health_check()
        fallback = adapter.run(symbol_or_market="BTCUSDT", payload={})
        await http_client.aclose()

        assert health["status"] == "unhealthy"
        assert health["stale_data_flag"] is True
        assert fallback.direction_bias == "neutral"
        assert fallback.scenario_confidence == 0.0
        assert fallback.provider_status == "degraded"

    asyncio.run(run())


def test_remote_sync_api_preserves_guarded_contract() -> None:
    adapter, http_client = _adapter()
    app = FastAPI()
    app.include_router(mirofish_router, prefix="/api/v1")
    app.state.mirofish_adapter = adapter
    payload = _sync_payload()
    payload["simulation_timestamp"] = payload["simulation_timestamp"].isoformat()  # type: ignore[union-attr]

    with TestClient(app) as client:
        response = client.post("/api/v1/simulation/mirofish/sync", json=payload)
        health = client.get("/api/v1/simulation/mirofish/health")

    asyncio.run(http_client.aclose())
    assert response.status_code == 200
    assert response.json()["advisory_only"] is True
    assert response.json()["scenario_confidence"] == 0.4
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"

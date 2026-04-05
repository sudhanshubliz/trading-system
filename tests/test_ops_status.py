from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.ops import router as ops_router
from app.live.types import LiveRiskLock
from app.ops.types import AlertPayload, IncidentSummary, OperatorStatus


class FakeOpsService:
    def __init__(self) -> None:
        self.operator_status = OperatorStatus(
            ops_enabled=True,
            deployment_mode="local",
            global_pause=False,
            live_enabled=True,
            live_armed=False,
            live_can_execute=False,
            active_locks=[
                LiveRiskLock(
                    lock_id="lock_001",
                    lock_type="LIVE_NOT_ARMED",
                    is_active=True,
                    reason="manual_disarm",
                    activated_at=datetime.now(timezone.utc),
                    metadata={},
                )
            ],
            market_data_status="ok",
            market_data_fresh=True,
            exchange_connectivity="configured",
            reconciliation_status="ok",
            open_live_positions=0,
            pending_approvals=2,
            daily_live_pnl=0.0,
            weekly_live_pnl=0.0,
            startup_status="ok",
            recovery_status="ok",
            warnings=[],
            timestamp=datetime.now(timezone.utc),
        )
        self.incidents = IncidentSummary(
            status="critical",
            active_lock_count=1,
            critical_event_count=0,
            pending_actions=["live_trading_is_disarmed"],
            items=[
                AlertPayload(
                    severity="critical",
                    category="live_lock",
                    message="LIVE_NOT_ARMED: manual_disarm",
                    source="live_lock_manager",
                    created_at=datetime.now(timezone.utc),
                    metadata={"lock_id": "lock_001"},
                )
            ],
            timestamp=datetime.now(timezone.utc),
        )

    async def get_operator_status(self) -> OperatorStatus:
        return self.operator_status

    async def get_incident_summary(self) -> IncidentSummary:
        return self.incidents

    async def run_recovery(self):
        raise RuntimeError("not used")


def test_ops_status_returns_expected_shape() -> None:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api/v1")
    app.state.ops_service = FakeOpsService()

    with TestClient(app) as client:
        response = client.get("/api/v1/ops/status")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "ops_enabled",
        "deployment_mode",
        "global_pause",
        "live_enabled",
        "live_armed",
        "live_can_execute",
        "active_locks",
        "market_data_status",
        "market_data_fresh",
        "exchange_connectivity",
        "reconciliation_status",
        "open_live_positions",
        "pending_approvals",
        "daily_live_pnl",
        "weekly_live_pnl",
        "startup_status",
        "recovery_status",
        "warnings",
        "timestamp",
    }


def test_operator_incidents_endpoint_includes_active_locks() -> None:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api/v1")
    app.state.ops_service = FakeOpsService()

    with TestClient(app) as client:
        response = client.get("/api/v1/ops/incidents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_lock_count"] == 1
    assert payload["items"][0]["category"] == "live_lock"

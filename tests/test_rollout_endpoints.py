from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.rollout import router as rollout_router
from app.live.types import RolloutHistoryEntry


class FakeLiveController:
    def _is_armed(self) -> bool:
        return True


class FakeRolloutService:
    def get_capital_status(self):
        return {
            "current_phase": "micro",
            "current_capital_limit": 100.0,
            "allowed_capital_limit": 100.0,
            "deployed_capital": 25.0,
            "remaining_capital": 75.0,
            "strategy_allocations": {"trend_follow_continuation": 25.0},
            "symbol_allocations": {"BTCUSDT": 25.0},
            "rollback_active": False,
            "last_phase_change_at": datetime.now(timezone.utc),
            "changed_by": "test",
            "reason": "seeded",
            "notes": ["note"],
            "timestamp": datetime.now(timezone.utc),
        }

    def list_phase_history(self):
        return [
            RolloutHistoryEntry(
                event_type="rollout_phase_changed",
                phase="micro",
                capital_limit=100.0,
                changed_by="test",
                reason="seeded",
                rollback_active=False,
                timestamp=datetime.now(timezone.utc),
            )
        ]


def test_rollout_status_endpoint_returns_expected_shape() -> None:
    app = FastAPI()
    app.include_router(rollout_router, prefix="/api/v1")
    app.state.rollout_service = FakeRolloutService()
    app.state.live_controller = FakeLiveController()

    with TestClient(app) as client:
        response = client.get("/api/v1/rollout/status")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "current_phase",
        "current_capital_limit",
        "allowed_capital_limit",
        "deployed_capital",
        "remaining_capital",
        "strategy_allocations",
        "symbol_allocations",
        "rollback_active",
        "last_phase_change_at",
        "changed_by",
        "reason",
        "notes",
        "live_effectively_allowed",
        "timestamp",
    }

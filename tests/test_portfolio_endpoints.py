from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.portfolio import router as portfolio_router


class FakePortfolioService:
    def get_portfolio_state(self, execution_mode: str = "paper"):
        return {
            "total_equity": 10000.0,
            "free_cash": 7800.0,
            "reserved_cash": 1000.0,
            "deployed_capital": 1200.0,
            "open_positions_count": 2,
            "open_positions_by_symbol": {"BTCUSDT": 1, "ETHUSDT": 1},
            "open_positions_by_strategy": {"trend_follow_continuation": 1, "breakout": 1},
            "pending_allocations": [],
            "active_rollout_phase": "n/a",
            "execution_mode": execution_mode,
            "strategy_allocations": {},
            "symbol_allocations": {},
            "correlation_clusters": {},
            "pending_candidate_count": 0,
            "rejected_candidate_count": 0,
            "position_sides_by_symbol": {"BTCUSDT": ["long"], "ETHUSDT": ["long"]},
            "timestamp": datetime.now(timezone.utc),
        }

    def get_allocations(self, execution_mode: str = "paper"):
        return {
            "execution_mode": execution_mode,
            "deployed_capital": 1200.0,
            "free_cash": 7800.0,
            "reserved_cash": 1000.0,
            "strategy_allocations": {},
            "symbol_allocations": {},
            "correlation_clusters": {},
            "pending_candidate_count": 0,
            "rejected_candidate_count": 0,
            "timestamp": datetime.now(timezone.utc),
        }

    def list_history(self, execution_mode: str | None = None, limit: int = 100):
        del execution_mode, limit
        return []


def test_portfolio_status_endpoint_returns_expected_shape() -> None:
    app = FastAPI()
    app.include_router(portfolio_router, prefix="/api/v1")
    app.state.portfolio_service = FakePortfolioService()

    with TestClient(app) as client:
        response = client.get("/api/v1/portfolio/status")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "total_equity",
        "free_cash",
        "reserved_cash",
        "deployed_capital",
        "open_positions_count",
        "open_positions_by_symbol",
        "open_positions_by_strategy",
        "pending_allocations",
        "active_rollout_phase",
        "execution_mode",
        "strategy_allocations",
        "symbol_allocations",
        "correlation_clusters",
        "pending_candidate_count",
        "rejected_candidate_count",
        "position_sides_by_symbol",
        "timestamp",
    }

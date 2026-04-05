from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db.models import SystemState
from app.db.session import SessionLocal
from app.execution.service import ExecutionService
from app.risk.types import RiskAssessment, RiskCheckResult


class FakeMarketDataService:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = prices

    async def get_snapshot(self, symbol: str) -> dict[str, float | None]:
        return {"last_price": self.prices.get(symbol.upper())}

    async def get_health(self) -> dict[str, str]:
        return {"status": "ok"}


class FakeRiskService:
    def __init__(self, assessments: list[RiskAssessment]) -> None:
        self._assessments = {assessment.assessment_id: assessment for assessment in assessments}

    def get_assessment(self, assessment_id: str) -> RiskAssessment | None:
        return self._assessments.get(assessment_id)


def _reset_global_pause() -> None:
    with SessionLocal() as session:
        state = session.get(SystemState, "global_pause")
        if state is None:
            state = SystemState(
                key="global_pause",
                value_json=json.dumps({"paused": False}),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(state)
        else:
            state.value_json = json.dumps({"paused": False})
            state.updated_at = datetime.now(timezone.utc)
        session.commit()


def _build_assessment(
    *,
    assessment_id: str,
    signal_id: str,
    symbol: str = "BTCUSDT",
    side: str = "long",
    entry_price: float = 100.0,
    stop_loss: float = 95.0,
    target_1: float = 110.0,
    target_2: float = 120.0,
    position_size: float = 10.0,
) -> RiskAssessment:
    return RiskAssessment(
        assessment_id=assessment_id,
        signal_id=signal_id,
        symbol=symbol,
        side=side,
        strategy_name="trend_follow_continuation",
        final_decision="approved_for_review",
        account_balance=10000.0,
        max_risk_pct=2.0,
        risk_amount=50.0,
        stop_distance_abs=5.0,
        stop_distance_pct=5.0,
        position_size=position_size,
        notional_value=entry_price * position_size,
        estimated_fee=1.0,
        estimated_slippage_pct=0.25,
        open_risk_pct_before=0.0,
        open_risk_pct_after=0.5,
        daily_drawdown_pct=0.0,
        weekly_drawdown_pct=0.0,
        min_reward_risk_ratio=1.5,
        actual_reward_risk_ratio=2.0,
        confidence_threshold=65,
        risk_score=85,
        trade_classification="A+",
        passed_checks_count=10,
        failed_checks_count=0,
        checks=[RiskCheckResult(name="dummy", passed=True)],
        rejection_reasons=[],
        generated_trade_plan={
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
            "position_size": position_size,
            "notional_value": entry_price * position_size,
            "mode": "paper",
            "approved_for_review": True,
        },
        assessed_at=datetime(2026, 4, 2, 15, 30, tzinfo=timezone.utc),
    )


def test_approval_creation() -> None:
    from app.main import app

    _reset_global_pause()
    assessment = _build_assessment(assessment_id="ras_approval_001", signal_id="sig_approval_001")

    with TestClient(app) as client:
        app.state.execution_service = ExecutionService(
            risk_service=FakeRiskService([assessment]),
            market_data_service=FakeMarketDataService({"BTCUSDT": 100.0}),
        )
        response = client.post("/api/v1/approvals/from-assessment/ras_approval_001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_id"] == "ras_approval_001"
    assert payload["status"] == "pending"


def test_approve_creates_trade_and_position() -> None:
    from app.main import app

    _reset_global_pause()
    assessment = _build_assessment(assessment_id="ras_exec_001", signal_id="sig_exec_001")

    with TestClient(app) as client:
        app.state.execution_service = ExecutionService(
            risk_service=FakeRiskService([assessment]),
            market_data_service=FakeMarketDataService({"BTCUSDT": 101.0}),
        )
        create_response = client.post("/api/v1/approvals/from-assessment/ras_exec_001")
        approval_id = create_response.json()["approval_id"]
        approve_response = client.post(f"/api/v1/approvals/{approval_id}/approve")
        trades_response = client.get("/api/v1/trades")
        positions_response = client.get("/api/v1/positions")

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "executed"
    assert trades_response.json()["count"] == 1
    assert positions_response.json()["count"] == 1


def test_reject_creates_no_trade() -> None:
    from app.main import app

    _reset_global_pause()
    assessment = _build_assessment(assessment_id="ras_reject_001", signal_id="sig_reject_001")

    with TestClient(app) as client:
        app.state.execution_service = ExecutionService(
            risk_service=FakeRiskService([assessment]),
            market_data_service=FakeMarketDataService({"BTCUSDT": 100.0}),
        )
        create_response = client.post("/api/v1/approvals/from-assessment/ras_reject_001")
        approval_id = create_response.json()["approval_id"]
        reject_response = client.post(f"/api/v1/approvals/{approval_id}/reject", json={"reason": "manual"})
        trades_response = client.get("/api/v1/trades")

    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert trades_response.json()["count"] == 0


def test_stop_loss_auto_close() -> None:
    from app.main import app

    _reset_global_pause()
    assessment = _build_assessment(assessment_id="ras_stop_001", signal_id="sig_stop_001")
    market_data = FakeMarketDataService({"BTCUSDT": 100.0})

    with TestClient(app) as client:
        app.state.execution_service = ExecutionService(
            risk_service=FakeRiskService([assessment]),
            market_data_service=market_data,
        )
        create_response = client.post("/api/v1/approvals/from-assessment/ras_stop_001")
        approval_id = create_response.json()["approval_id"]
        client.post(f"/api/v1/approvals/{approval_id}/approve")
        market_data.prices["BTCUSDT"] = 94.0
        positions_response = client.get("/api/v1/positions")

    position = positions_response.json()["items"][0]
    assert position["status"] == "closed"
    assert position["close_reason"] == "stop_loss"


def test_target_hit_updates_pnl() -> None:
    from app.main import app

    _reset_global_pause()
    assessment = _build_assessment(assessment_id="ras_target_001", signal_id="sig_target_001")
    market_data = FakeMarketDataService({"BTCUSDT": 100.0})

    with TestClient(app) as client:
        app.state.execution_service = ExecutionService(
            risk_service=FakeRiskService([assessment]),
            market_data_service=market_data,
        )
        create_response = client.post("/api/v1/approvals/from-assessment/ras_target_001")
        approval_id = create_response.json()["approval_id"]
        client.post(f"/api/v1/approvals/{approval_id}/approve")
        market_data.prices["BTCUSDT"] = 110.0
        positions_response = client.get("/api/v1/positions")

    position = positions_response.json()["items"][0]
    assert position["target_1_hit"] is True
    assert position["realized_pnl"] > 0
    assert position["quantity_open"] < position["initial_quantity"]


def test_pnl_endpoint_returns_correct_structure() -> None:
    from app.main import app

    _reset_global_pause()
    assessment = _build_assessment(assessment_id="ras_pnl_001", signal_id="sig_pnl_001")
    market_data = FakeMarketDataService({"BTCUSDT": 100.0})

    with TestClient(app) as client:
        app.state.execution_service = ExecutionService(
            risk_service=FakeRiskService([assessment]),
            market_data_service=market_data,
        )
        create_response = client.post("/api/v1/approvals/from-assessment/ras_pnl_001")
        approval_id = create_response.json()["approval_id"]
        client.post(f"/api/v1/approvals/{approval_id}/approve")
        pnl_response = client.get("/api/v1/pnl")

    assert pnl_response.status_code == 200
    payload = pnl_response.json()
    for key in [
        "realized_pnl_total",
        "unrealized_pnl_total",
        "daily_pnl",
        "open_positions",
        "closed_positions",
        "total_trades",
        "timestamp",
    ]:
        assert key in payload


def test_pause_prevents_execution() -> None:
    from app.main import app

    _reset_global_pause()
    assessment = _build_assessment(assessment_id="ras_pause_001", signal_id="sig_pause_001")

    with TestClient(app) as client:
        app.state.execution_service = ExecutionService(
            risk_service=FakeRiskService([assessment]),
            market_data_service=FakeMarketDataService({"BTCUSDT": 100.0}),
        )
        create_response = client.post("/api/v1/approvals/from-assessment/ras_pause_001")
        approval_id = create_response.json()["approval_id"]
        pause_response = client.post("/api/v1/control/pause")
        approve_response = client.post(f"/api/v1/approvals/{approval_id}/approve")
        trades_response = client.get("/api/v1/trades")
        client.post("/api/v1/control/resume")

    assert pause_response.status_code == 200
    assert pause_response.json()["paused"] is True
    assert approve_response.status_code == 409
    assert trades_response.json()["count"] == 0

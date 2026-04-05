from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.risk.service import RiskService
from app.signals.types import CandidateSignal


class HealthyMarketDataService:
    async def get_health(self) -> dict[str, object]:
        return {"status": "ok"}


class FakeSignalService:
    async def evaluate_symbols(self, symbols: list[str] | None = None) -> list[CandidateSignal]:
        return [
            CandidateSignal(
                signal_id="sig_valid_001",
                symbol="BTCUSDT",
                side="long",
                strategy_name="trend_follow_continuation",
                confidence_score=78,
                entry_price=68250.5,
                stop_loss=67600.0,
                target_1=69325.5,
                target_2=69876.0,
                reward_risk_ratio=1.5,
                rationale=[
                    "1h bullish trend confirmed by EMA alignment",
                    "15m pullback near VWAP",
                    "5m momentum recovery confirmed",
                ],
                indicators_snapshot={},
                generated_at=datetime(2026, 4, 2, 15, 30, tzinfo=timezone.utc),
                status="candidate",
            )
        ]


def test_risk_validate_endpoint_approves_valid_signal() -> None:
    from app.main import app

    market_data_service = HealthyMarketDataService()

    payload = {
        "signal_id": "sig_validate_ok",
        "symbol": "BTCUSDT",
        "side": "long",
        "strategy_name": "trend_follow_continuation",
        "confidence_score": 80,
        "entry_price": 68250.5,
        "stop_loss": 67600.0,
        "target_1": 69325.5,
        "target_2": 69876.0,
        "reward_risk_ratio": 1.66,
        "rationale": ["Aligned and valid"],
        "generated_at": "2026-04-02T15:30:00Z",
    }

    with TestClient(app) as client:
        app.state.risk_service = RiskService(market_data_service=market_data_service)
        response = client.post("/api/v1/risk/validate", json=payload)

    assert response.status_code == 200
    result = response.json()
    assert result["final_decision"] == "approved_for_review"
    assert result["position_size"] is not None
    assert result["rejection_reasons"] == []


def test_risk_validate_endpoint_rejects_low_confidence() -> None:
    from app.main import app

    market_data_service = HealthyMarketDataService()

    payload = {
        "signal_id": "sig_validate_low_conf",
        "symbol": "BTCUSDT",
        "side": "long",
        "strategy_name": "trend_follow_continuation",
        "confidence_score": 40,
        "entry_price": 68250.5,
        "stop_loss": 67600.0,
        "target_1": 69325.5,
        "target_2": 69876.0,
        "reward_risk_ratio": 1.66,
        "rationale": ["Low confidence"],
        "generated_at": "2026-04-02T15:30:00Z",
    }

    with TestClient(app) as client:
        app.state.risk_service = RiskService(market_data_service=market_data_service)
        response = client.post("/api/v1/risk/validate", json=payload)

    assert response.status_code == 200
    result = response.json()
    assert result["final_decision"] == "rejected"
    assert "confidence_below_threshold" in result["rejection_reasons"]


def test_risk_evaluate_signals_endpoint_returns_items() -> None:
    from app.main import app

    signal_service = FakeSignalService()
    market_data_service = HealthyMarketDataService()

    with TestClient(app) as client:
        app.state.signal_service = signal_service
        app.state.risk_service = RiskService(
            signal_service=signal_service,
            market_data_service=market_data_service,
        )
        response = client.post("/api/v1/risk/evaluate-signals", json={"symbols": ["BTCUSDT"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1

    first_item = payload["items"][0]
    for key in [
        "assessment_id",
        "signal_id",
        "final_decision",
        "account_balance",
        "risk_amount",
        "stop_distance_abs",
        "stop_distance_pct",
        "position_size",
        "notional_value",
        "checks",
        "rejection_reasons",
        "generated_trade_plan",
        "assessed_at",
    ]:
        assert key in first_item

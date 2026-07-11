from __future__ import annotations

import asyncio
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

    def get_signals(self, **_: object) -> list[CandidateSignal]:
        return []


class CachedOnlySignalService:
    def __init__(self) -> None:
        self._signal = CandidateSignal(
            signal_id="sig_cached_001",
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

    async def evaluate_symbols(self, symbols: list[str] | None = None) -> list[CandidateSignal]:
        return []

    def get_signals(self, **_: object) -> list[CandidateSignal]:
        return [self._signal]


def _valid_risk_payload(signal_id: str) -> dict[str, object]:
    return {
        "signal_id": signal_id,
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
        "generated_at": datetime(2026, 4, 2, 15, 30, tzinfo=timezone.utc),
    }


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


def test_releasing_assessment_reservation_restores_risk_capacity() -> None:
    from app.config.settings import get_settings

    settings = get_settings().model_copy(
        update={
            "max_concurrent_positions": 1,
            "paper_account_start_balance": 5000.0,
            "strategy_trade_cooldown_minutes": 0,
        }
    )
    service = RiskService(
        settings=settings,
        market_data_service=HealthyMarketDataService(),
    )

    first = asyncio.run(service.validate_signal_payload(_valid_risk_payload("sig_reservation_first")))
    blocked = asyncio.run(service.validate_signal_payload(_valid_risk_payload("sig_reservation_blocked")))
    released = service.release_assessment_reservation(first.assessment_id)
    after_release = asyncio.run(service.validate_signal_payload(_valid_risk_payload("sig_reservation_after_release")))

    assert first.final_decision == "approved_for_review"
    assert "max_concurrent_positions_reached" in blocked.rejection_reasons
    assert released is True
    assert after_release.final_decision == "approved_for_review"


def test_risk_rejects_low_net_edge_and_rapid_reentry() -> None:
    from app.config.settings import get_settings

    fixed_now = datetime(2026, 4, 2, 15, 30, tzinfo=timezone.utc)
    settings = get_settings().model_copy(
        update={
            "enable_cost_aware_trade_filter": True,
            "min_net_edge_after_costs_bps": 8.0,
            "strategy_trade_cooldown_minutes": 240,
            "max_concurrent_positions": 3,
        }
    )
    service = RiskService(
        settings=settings,
        market_data_service=HealthyMarketDataService(),
        time_provider=lambda: fixed_now,
    )

    first = asyncio.run(service.validate_signal_payload(_valid_risk_payload("sig_cost_first")))
    rapid_reentry = asyncio.run(service.validate_signal_payload(_valid_risk_payload("sig_cost_reentry")))

    low_edge_settings = settings.model_copy(update={"strategy_trade_cooldown_minutes": 0})
    low_edge_service = RiskService(
        settings=low_edge_settings,
        market_data_service=HealthyMarketDataService(),
        time_provider=lambda: fixed_now,
    )
    low_edge_payload = _valid_risk_payload("sig_cost_low_edge")
    low_edge_payload.update(
        {
            "confidence_score": 65,
            "stop_loss": 67909.25,
            "target_1": 68591.75,
            "reward_risk_ratio": 1.0,
        }
    )
    low_edge = asyncio.run(low_edge_service.validate_signal_payload(low_edge_payload))

    assert first.final_decision == "approved_for_review"
    assert "strategy_turnover_cooldown_active" in rapid_reentry.rejection_reasons
    assert "net_edge_after_costs_below_minimum" in low_edge.rejection_reasons
    assert low_edge.generated_trade_plan["estimated_round_trip_cost_bps"] == 28.0


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


def test_risk_evaluate_signals_uses_fresh_cached_signal_when_generation_dedupes() -> None:
    from app.main import app

    signal_service = CachedOnlySignalService()
    market_data_service = HealthyMarketDataService()
    fixed_now = datetime(2026, 4, 2, 15, 34, tzinfo=timezone.utc)

    with TestClient(app) as client:
        app.state.signal_service = signal_service
        app.state.risk_service = RiskService(
            signal_service=signal_service,
            market_data_service=market_data_service,
            time_provider=lambda: fixed_now,
        )
        response = client.post("/api/v1/risk/evaluate-signals", json={"symbols": ["BTCUSDT"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["signal_id"] == "sig_cached_001"


def test_risk_validate_resizes_oversized_paper_notional_instead_of_rejecting() -> None:
    from app.main import app
    from app.config.settings import get_settings

    market_data_service = HealthyMarketDataService()
    settings = get_settings().model_copy(
        update={
            "execution_mode": "paper",
            "paper_account_start_balance": 10000.0,
            "max_risk_per_trade_pct": 2.0,
            "paper_max_position_notional_pct_of_balance": 100.0,
        }
    )

    payload = {
        "signal_id": "sig_validate_resized",
        "symbol": "ETHUSDT",
        "side": "long",
        "strategy_name": "trend_follow_continuation",
        "confidence_score": 83,
        "entry_price": 2103.99,
        "stop_loss": 2092.26,
        "target_1": 2121.585,
        "target_2": 2133.315,
        "reward_risk_ratio": 1.5,
        "rationale": ["Tight stop but otherwise valid"],
        "generated_at": "2026-05-25T04:49:37Z",
    }

    with TestClient(app) as client:
        app.state.risk_service = RiskService(settings=settings, market_data_service=market_data_service)
        response = client.post("/api/v1/risk/validate", json=payload)

    assert response.status_code == 200
    result = response.json()
    assert result["final_decision"] == "approved_for_review"
    assert result["notional_value"] <= settings.paper_account_start_balance
    assert result["generated_trade_plan"]["notional_capped"] is True
    assert result["generated_trade_plan"]["max_position_notional"] == settings.paper_account_start_balance

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.strategy_owner import router as strategy_owner_router
from app.config.settings import get_settings
from app.execution_quality.service import ExecutionQualityService
from app.market_data.types import OrderBookLevel, OrderBookSnapshot, TickerSnapshot
from app.persistence.db import get_persistence_engine, get_persistence_session_factory
from app.persistence.models import PersistenceBase
from app.persistence.repositories.execution_quality_repo import ExecutionQualityRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.strategy_owner_repo import StrategyOwnerRepository
from app.provider_health.service import ProviderHealthService
from app.provider_health.types import ProviderHealthSnapshot
from app.promotion.service import PromotionService
from app.regime.types import RegimeSnapshot
from app.risk.types import AccountState, ExposureState, RiskAssessment, RiskCheckResult, RiskSummary
from app.signals.types import CandidateSignal
from app.strategy_owner.service import StrategyOwnerService
from app.wallet_intel.types import WalletSignal


class StubSignalService:
    async def evaluate_symbols(self, symbols: list[str] | None = None):
        generated_at = datetime.now(timezone.utc)
        return [
            CandidateSignal(
                signal_id="sig_btc_long",
                symbol="BTCUSDT",
                side="long",
                strategy_name="trend_follow_continuation",
                confidence_score=74,
                entry_price=68500.0,
                stop_loss=68100.0,
                target_1=69150.0,
                target_2=69550.0,
                reward_risk_ratio=1.8,
                rationale=["trend intact", "trigger confirmed"],
                indicators_snapshot={},
                generated_at=generated_at,
            )
        ]


class StubWalletService:
    def list_signals(self, *, wallet_id: str | None = None, limit: int = 100):
        return [
            WalletSignal(
                signal_id="wal_sig_weak",
                wallet_id="wal_alpha",
                symbol_or_market="BTCUSDT",
                timestamp=datetime.now(timezone.utc),
                direction="long",
                confidence=0.35,
                rationale=["crowded wallet flow"],
                quality_score_snapshot=0.3,
                crowding_risk=0.82,
                recommended_action="monitor",
            )
        ]


class StubMarketDataService:
    async def get_snapshot(self, symbol: str):
        now = datetime.now(timezone.utc)
        return TickerSnapshot(
            symbol=symbol.upper(),
            last_price=68520.0,
            bid_price=68518.0,
            ask_price=68522.0,
            spread_bps=0.58,
            ticker_updated_at=now,
            orderbook_updated_at=now,
        )

    async def get_order_book(self, symbol: str):
        now = datetime.now(timezone.utc)
        return OrderBookSnapshot(
            symbol=symbol.upper(),
            bids=[OrderBookLevel(price=68518.0, quantity=1.8), OrderBookLevel(price=68517.5, quantity=2.1)],
            asks=[OrderBookLevel(price=68522.0, quantity=1.7), OrderBookLevel(price=68522.5, quantity=1.9)],
            updated_at=now,
        )


class StubProviderHealthService(ProviderHealthService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        observed_at = datetime.now(timezone.utc)
        for provider_name in ("binance_spot_market_data", "binance_futures_market_data", "wallet_intel"):
            self._latest[provider_name] = ProviderHealthSnapshot(
                snapshot_id=f"phs_{provider_name}",
                provider_name=provider_name,
                status="healthy",
                latency_ms=50.0,
                success_rate=1.0,
                stale_data_flag=False,
                error_count=0,
                last_success_at=observed_at,
                last_failure_at=None,
                observed_at=observed_at,
            )


class StubRegimeService:
    def get_current(self, symbol: str):
        return RegimeSnapshot(
            snapshot_id="reg_btc",
            symbol=symbol.upper(),
            regime="trending_up",
            confidence=0.8,
            generated_at=datetime.now(timezone.utc),
            trend_score=0.7,
            volatility_score=0.3,
            compression_score=0.2,
            mean_reversion_score=0.1,
            supporting_factors=["trend_strength_positive"],
            veto_factors=[],
            metadata={},
        )


class StubRiskService:
    def get_summary(self):
        return RiskSummary(
            account_balance=10000.0,
            equity=10000.0,
            available_balance=10000.0,
            open_risk_pct=0.0,
            daily_drawdown_pct=0.0,
            weekly_drawdown_pct=0.0,
            max_risk_per_trade_pct=2.0,
            max_concurrent_positions=3,
            open_positions=0,
            global_risk_lock=False,
            timestamp=datetime.now(timezone.utc),
        )

    def list_current_locks(self):
        return []

    async def validate_signal_payload(self, payload):
        return RiskAssessment(
            assessment_id="ras_sig_btc_long",
            signal_id=payload.signal_id,
            symbol=payload.symbol,
            side=payload.side,
            strategy_name=payload.strategy_name,
            final_decision="approved_for_review",
            account_balance=10000.0,
            max_risk_pct=2.0,
            risk_amount=100.0,
            stop_distance_abs=400.0,
            stop_distance_pct=0.58,
            position_size=0.1,
            notional_value=6850.0,
            estimated_fee=5.0,
            estimated_slippage_pct=0.05,
            open_risk_pct_before=0.0,
            open_risk_pct_after=1.0,
            daily_drawdown_pct=0.0,
            weekly_drawdown_pct=0.0,
            min_reward_risk_ratio=1.5,
            actual_reward_risk_ratio=1.8,
            confidence_threshold=65,
            risk_score=85,
            trade_classification="paper_candidate",
            passed_checks_count=5,
            failed_checks_count=0,
            checks=[RiskCheckResult(name="confidence", passed=True)],
            rejection_reasons=[],
            generated_trade_plan={"allowed": True},
            active_risk_locks=[],
            assessed_at=datetime.now(timezone.utc),
        )


def _build_service(tmp_path: Path) -> StrategyOwnerService:
    settings = get_settings().model_copy(
        update={
            "persistence_db_url": f"sqlite:///{tmp_path / 'strategy_owner.db'}",
            "signals_supported_symbols": ["BTCUSDT"],
            "strategy_owner_min_expected_value_bps": 4.0,
            "strategy_owner_min_overall_score": 0.52,
        }
    )
    engine = get_persistence_engine(settings.persistence_db_url)
    PersistenceBase.metadata.create_all(bind=engine)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    events_repo = EventsRepository(session_factory)
    repo = StrategyOwnerRepository(session_factory)
    provider_health_service = StubProviderHealthService(
        settings=settings,
        events_repo=events_repo,
    )
    execution_quality_service = ExecutionQualityService(
        settings=settings,
        repo=ExecutionQualityRepository(session_factory),
        events_repo=events_repo,
    )
    promotion_service = PromotionService(
        settings=settings,
        execution_quality_service=execution_quality_service,
        trades_repo=None,
        provider_health_service=provider_health_service,
        events_repo=events_repo,
        repo=None,
    )
    return StrategyOwnerService(
        settings=settings,
        signal_service=StubSignalService(),
        wallet_intel_service=StubWalletService(),
        market_data_service=StubMarketDataService(),
        provider_health_service=provider_health_service,
        execution_quality_service=execution_quality_service,
        regime_service=StubRegimeService(),
        promotion_service=promotion_service,
        risk_service=StubRiskService(),
        repo=repo,
        events_repo=events_repo,
    )


def test_strategy_owner_evaluates_and_persists_candidates(tmp_path: Path) -> None:
    service = _build_service(tmp_path)

    result = __import__("asyncio").run(service.evaluate(symbols=["BTCUSDT"]))

    assert result.accepted_count == 1
    assert result.forwarded_to_risk_count == 1
    assert result.rejected_count == 1
    assert any(item.status == "accepted_for_risk" for item in result.decisions)
    assert any(item.status == "rejected" and item.rejection_reason for item in result.decisions)
    assert service.list_candidates(limit=10)
    assert service.list_rejections(limit=10)


def test_strategy_owner_api_exposes_decisions_and_rejections(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    __import__("asyncio").run(service.evaluate(symbols=["BTCUSDT"]))

    app = FastAPI()
    app.include_router(strategy_owner_router, prefix="/api/v1")
    app.state.strategy_owner_service = service

    client = TestClient(app)

    summary = client.get("/api/v1/strategy-owner/summary")
    assert summary.status_code == 200
    assert summary.json()["accepted_count"] == 1

    decisions = client.get("/api/v1/strategy-owner/decisions")
    assert decisions.status_code == 200
    assert decisions.json()["count"] == 2

    rejections = client.get("/api/v1/strategy-owner/rejections")
    assert rejections.status_code == 200
    assert rejections.json()["count"] == 1

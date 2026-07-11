from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.alpha_fusion.service import AlphaFusionService
from app.api.routes.alpha import router as alpha_router
from app.api.routes.arbitrage import router as arbitrage_router
from app.api.routes.execution_quality import router as execution_quality_router
from app.api.routes.microstructure import router as microstructure_router
from app.api.routes.risk import router as risk_router
from app.api.routes.system_intelligence import router as system_router
from app.arbitrage.service import BasisFundingService
from app.config.settings import get_settings
from app.execution.types import Approval, Trade
from app.execution_quality.service import ExecutionQualityService
from app.features.microstructure.service import MicrostructureService
from app.features.service import FeatureService
from app.market_data.types import Candle, FundingRatePoint, FundingSnapshot, OrderBookLevel, OrderBookSnapshot, TickerSnapshot, TradePrint
from app.persistence.db import get_persistence_engine, get_persistence_session_factory
from app.persistence.models import PersistenceBase
from app.persistence.repositories.alpha_fusion_repo import AlphaFusionRepository
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.arbitrage_repo import ArbitrageRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.execution_quality_repo import ExecutionQualityRepository
from app.persistence.repositories.feature_runs_repo import FeatureRunsRepository
from app.persistence.repositories.fused_opportunities_repo import FusedOpportunitiesRepository
from app.persistence.repositories.microstructure_repo import MicrostructureRepository
from app.persistence.repositories.regime_repo import RegimeRepository
from app.persistence.repositories.risk_lock_events_repo import RiskLockEventsRepository
from app.regime.service import RegimeService
from app.replay.service import ReplayService
from app.risk.locks import RiskLockManager
from app.risk.service import RiskService
from app.risk.types import RiskAssessment


def _make_candles(
    *,
    count: int,
    start_price: float,
    step: float,
    start_time: datetime,
    minutes: int,
    premium_bps: float = 0.0,
) -> list[Candle]:
    candles: list[Candle] = []
    price = start_price
    for index in range(count):
        current_open = price
        current_close = current_open + step
        if premium_bps:
            current_open *= 1 + premium_bps / 10000
            current_close *= 1 + premium_bps / 10000
        candles.append(
            Candle(
                open_time=start_time + timedelta(minutes=minutes * index),
                open=current_open,
                high=max(current_open, current_close) * 1.002,
                low=min(current_open, current_close) * 0.998,
                close=current_close,
                volume=180 + index * 3,
                is_closed=True,
            )
        )
        price += step
    return candles


class FakePhase2MarketDataService:
    def __init__(
        self,
        *,
        stale_book: bool = False,
        thin_liquidity: bool = False,
        toxic_flow: bool = False,
        missing_funding: bool = False,
    ) -> None:
        now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
        self.now = now
        base_1h = now - timedelta(hours=39)
        base_5m = now - timedelta(minutes=5 * 59)
        self.spot_1h = _make_candles(count=40, start_price=67000.0, step=24.0, start_time=base_1h, minutes=60)
        self.futures_1h = _make_candles(
            count=40,
            start_price=67000.0,
            step=24.0,
            start_time=base_1h,
            minutes=60,
            premium_bps=22.0,
        )
        self.spot_5m = _make_candles(count=60, start_price=68400.0, step=3.0, start_time=base_5m, minutes=5)
        self._stale_book = stale_book
        self._thin_liquidity = thin_liquidity
        self._toxic_flow = toxic_flow
        self._missing_funding = missing_funding

    async def get_health(self) -> dict[str, str]:
        return {"status": "ok"}

    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        if timeframe.lower() == "1h":
            return self.spot_1h
        return self.spot_5m

    async def get_futures_candles(self, symbol: str, timeframe: str, limit: int | None = None) -> list[Candle]:
        candles = self.futures_1h if timeframe.lower() == "1h" else self.spot_5m
        return candles[-limit:] if limit else candles

    async def get_snapshot(self, symbol: str) -> TickerSnapshot:
        latest = self.spot_5m[-1]
        spread_bps = 18.0 if self._thin_liquidity else 1.8
        return TickerSnapshot(
            symbol=symbol.upper(),
            last_price=latest.close,
            bid_price=latest.close * (1 - spread_bps / 20000),
            ask_price=latest.close * (1 + spread_bps / 20000),
            best_bid_qty=0.08 if self._thin_liquidity else 4.5,
            best_ask_qty=0.08 if self._thin_liquidity else 3.8,
            spread_bps=spread_bps,
            snapshot_time=self.now,
        )

    async def get_order_book(self, symbol: str) -> OrderBookSnapshot:
        latest = self.spot_5m[-1]
        updated_at = self.now - timedelta(seconds=120) if self._stale_book else self.now
        spread_bps = 25.0 if self._thin_liquidity else 1.5
        top_notional = 500.0 if self._thin_liquidity else 45000.0
        bids = []
        asks = []
        for level in range(5):
            distance_bps = spread_bps / 2 + level * max(spread_bps, 1.0)
            bid_price = latest.close * (1 - distance_bps / 10000)
            ask_price = latest.close * (1 + distance_bps / 10000)
            bid_notional = top_notional * (1.45 if not self._thin_liquidity else 1.0) / (level + 1)
            ask_notional = top_notional * (0.85 if not self._thin_liquidity else 1.0) / (level + 1)
            bids.append(OrderBookLevel(price=bid_price, quantity=bid_notional / bid_price))
            asks.append(OrderBookLevel(price=ask_price, quantity=ask_notional / ask_price))
        return OrderBookSnapshot(
            symbol=symbol.upper(),
            bids=bids,
            asks=asks,
            updated_at=updated_at,
            update_count_1s=24 if self._toxic_flow else 4,
            update_count_5s=100 if self._toxic_flow else 12,
        )

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[TradePrint]:
        latest = self.spot_5m[-1]
        trades: list[TradePrint] = []
        for index in range(min(limit, 30)):
            if self._toxic_flow:
                price = latest.close * (1 + ((-1) ** index) * 0.004)
                is_buyer_maker = index % 2 == 0
            else:
                price = latest.close * (1 + index * 0.0001)
                is_buyer_maker = index % 6 == 0
            trades.append(
                TradePrint(
                    symbol=symbol.upper(),
                    price=price,
                    quantity=0.4 + index * 0.03,
                    is_buyer_maker=is_buyer_maker,
                    trade_time=self.now - timedelta(seconds=30 - index),
                )
            )
        return trades

    async def get_funding_snapshot(self, symbol: str) -> FundingSnapshot | None:
        if self._missing_funding:
            return None
        latest_spot = self.spot_1h[-1]
        latest_futures = self.futures_1h[-1]
        fetched_at = self.now - timedelta(seconds=5000) if self._stale_book else self.now
        return FundingSnapshot(
            symbol=symbol.upper(),
            mark_price=latest_futures.close,
            index_price=latest_spot.close,
            last_funding_rate=0.0009,
            next_funding_time=self.now + timedelta(hours=4),
            fetched_at=fetched_at,
        )

    async def get_funding_history(self, symbol: str, limit: int = 50) -> list[FundingRatePoint]:
        history: list[FundingRatePoint] = []
        for index, candle in enumerate(self.futures_1h[-limit:]):
            history.append(
                FundingRatePoint(
                    symbol=symbol.upper(),
                    funding_rate=0.00012 + index * 0.00001,
                    funding_time=candle.open_time,
                    mark_price=candle.close,
                )
            )
        return history


def _settings(**updates: object):
    defaults = {
        "signals_supported_symbols": ["BTCUSDT"],
        "alpha_feature_timeframes": ["5m", "1h"],
        "basis_history_limit": 24,
        "basis_zscore_action_threshold": 1.0,
        "basis_min_net_edge_bps": 2.0,
        "microstructure_top_n_levels": 5,
        "microstructure_min_depth_usd": 5000.0,
        "microstructure_max_relative_spread_bps": 5.0,
        "microstructure_stale_book_seconds": 30,
        "microstructure_vol_shock_threshold": 0.2,
        "execution_quality_bad_score_threshold": 0.65,
        "enable_stale_data_lock": True,
        "enable_volatility_shock_lock": True,
        "enable_execution_anomaly_lock": True,
        "enable_liquidity_thin_lock": True,
        "enable_basis_data_integrity_lock": True,
    }
    defaults.update(updates)
    return get_settings().model_copy(update=defaults)


def _candidate_payload(now: datetime) -> dict[str, object]:
    return {
        "signal_id": "sig_phase2_lock",
        "symbol": "BTCUSDT",
        "side": "long",
        "strategy_name": "trend_follow_continuation",
        "confidence_score": 85,
        "entry_price": 68550.0,
        "stop_loss": 68200.0,
        "target_1": 69100.0,
        "target_2": 69450.0,
        "reward_risk_ratio": 1.8,
        "rationale": ["phase2 lock validation"],
        "generated_at": now,
        "metadata": {},
    }


def _make_trade(now: datetime, *, trade_id: str, fill_price: float) -> Trade:
    return Trade(
        trade_id=trade_id,
        approval_id=f"apr_{trade_id}",
        assessment_id=f"asm_{trade_id}",
        signal_id=f"sig_{trade_id}",
        position_id=f"pos_{trade_id}",
        symbol="BTCUSDT",
        side="long",
        strategy_name="trend_follow_continuation",
        quantity=0.25,
        execution_price=fill_price,
        requested_entry_price=68500.0,
        stop_loss=68200.0,
        target_1=69100.0,
        target_2=69450.0,
        status="open",
        execution_mode="paper",
        opened_at=now,
        updated_at=now,
    )


def _make_approval(now: datetime, *, trade_id: str) -> Approval:
    return Approval(
        approval_id=f"apr_{trade_id}",
        assessment_id=f"asm_{trade_id}",
        signal_id=f"sig_{trade_id}",
        symbol="BTCUSDT",
        side="long",
        strategy_name="trend_follow_continuation",
        status="approved",
        created_at=now - timedelta(seconds=4),
        approved_at=now - timedelta(seconds=3),
    )


def _make_assessment(now: datetime, *, signal_id: str) -> RiskAssessment:
    return RiskAssessment(
        assessment_id=f"asm_{signal_id}",
        signal_id=signal_id,
        symbol="BTCUSDT",
        side="long",
        strategy_name="trend_follow_continuation",
        final_decision="approved_for_review",
        account_balance=100000.0,
        max_risk_pct=1.0,
        risk_amount=1000.0,
        stop_distance_abs=300.0,
        stop_distance_pct=0.45,
        position_size=0.25,
        notional_value=17000.0,
        estimated_fee=10.0,
        estimated_slippage_pct=0.1,
        open_risk_pct_before=0.0,
        open_risk_pct_after=0.25,
        daily_drawdown_pct=0.0,
        weekly_drawdown_pct=0.0,
        min_reward_risk_ratio=1.5,
        actual_reward_risk_ratio=1.8,
        confidence_threshold=60,
        risk_score=85,
        trade_classification="high_confidence",
        passed_checks_count=8,
        failed_checks_count=0,
        assessed_at=now - timedelta(seconds=3),
    )


def test_basis_funding_engine_classifies_tradable_opportunity() -> None:
    settings = _settings()
    market_data = FakePhase2MarketDataService()
    service = BasisFundingService(settings=settings, market_data_service=market_data, time_provider=lambda: market_data.now)

    opportunity = asyncio.run(service.evaluate_symbol("BTCUSDT"))

    assert opportunity is not None
    assert opportunity.signal_family == "basis_funding"
    assert opportunity.opportunity_type in {"actionable_short_basis_reversion", "carry_like_positive"}
    assert opportunity.tradable is True
    assert opportunity.net_edge_estimate >= settings.basis_min_net_edge_bps
    assert opportunity.basis_zscore is not None


def test_microstructure_engine_extracts_features_and_detects_stale_data() -> None:
    settings = _settings()
    normal_market = FakePhase2MarketDataService()
    service = MicrostructureService(settings=settings, market_data_service=normal_market, time_provider=lambda: normal_market.now)

    snapshot = asyncio.run(service.compute_symbol("BTCUSDT"))

    assert snapshot is not None
    assert snapshot.top_of_book_spread_bps is not None
    assert snapshot.microprice is not None
    assert snapshot.market_state in {"imbalance_buy_pressure", "normal"}
    assert snapshot.signal_policy in {"passive_buy_bias", "taker_buy_momentum", "no_trade"}

    stale_market = FakePhase2MarketDataService(stale_book=True)
    stale_service = MicrostructureService(settings=settings, market_data_service=stale_market, time_provider=lambda: stale_market.now)
    stale_snapshot = asyncio.run(stale_service.compute_symbol("BTCUSDT"))

    assert stale_snapshot is not None
    assert stale_snapshot.stale_book is True
    assert stale_snapshot.market_state == "stale_data"
    assert stale_snapshot.signal_policy == "unsafe_to_trade"


def test_execution_quality_scoring_and_anomaly_detection() -> None:
    settings = _settings()
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    service = ExecutionQualityService(settings=settings)
    snapshot = TickerSnapshot(
        symbol="BTCUSDT",
        last_price=68500.0,
        bid_price=68495.0,
        ask_price=68505.0,
        spread_bps=12.0,
        snapshot_time=now,
    )

    for index in range(3):
        record = service.record_execution(
            trade=_make_trade(now + timedelta(seconds=index), trade_id=f"t{index}", fill_price=69050.0 + index),
            approval=_make_approval(now + timedelta(seconds=index), trade_id=f"t{index}"),
            assessment=_make_assessment(now + timedelta(seconds=index), signal_id=f"sig_t{index}"),
            snapshot=snapshot,
            mode="paper",
            execution_policy="simulation_only",
            partial_fill_ratio=0.45,
        )
        assert record.fill_quality_score < 0.65

    anomaly = service.recent_anomaly_state(limit=5)
    assert anomaly["bad_record_count"] == 3
    assert anomaly["is_anomalous"] is True


def test_phase2_risk_locks_veto_trades_for_stale_thin_toxic_and_integrity_failures() -> None:
    settings = _settings()

    async def assess_for(market_data: FakePhase2MarketDataService, *, seed_bad_exec: bool = False):
        execution_quality = ExecutionQualityService(settings=settings)
        if seed_bad_exec:
            snapshot = await market_data.get_snapshot("BTCUSDT")
            now = market_data.now
            for index in range(3):
                execution_quality.record_execution(
                    trade=_make_trade(now + timedelta(seconds=index), trade_id=f"anom_{index}", fill_price=69050.0),
                    approval=_make_approval(now + timedelta(seconds=index), trade_id=f"anom_{index}"),
                    assessment=_make_assessment(now + timedelta(seconds=index), signal_id=f"anom_{index}"),
                    snapshot=snapshot,
                    mode="paper",
                    execution_policy="simulation_only",
                    partial_fill_ratio=0.4,
                )
        microstructure = MicrostructureService(settings=settings, market_data_service=market_data, time_provider=lambda: market_data.now)
        await microstructure.compute_symbol("BTCUSDT")
        arbitrage = BasisFundingService(settings=settings, market_data_service=market_data, time_provider=lambda: market_data.now)
        risk_service = RiskService(
            settings=settings,
            market_data_service=market_data,
            time_provider=lambda: market_data.now,
            risk_lock_manager=RiskLockManager(),
            execution_quality_service=execution_quality,
            arbitrage_service=arbitrage,
            microstructure_service=microstructure,
        )
        return await risk_service.validate_signal_payload(_candidate_payload(market_data.now))

    stale_assessment = asyncio.run(assess_for(FakePhase2MarketDataService(stale_book=True)))
    assert any(item["lock_type"] == "stale_data_lock" for item in stale_assessment.active_risk_locks)

    thin_assessment = asyncio.run(assess_for(FakePhase2MarketDataService(thin_liquidity=True)))
    assert any(item["lock_type"] == "liquidity_thin_lock" for item in thin_assessment.active_risk_locks)

    toxic_assessment = asyncio.run(assess_for(FakePhase2MarketDataService(toxic_flow=True)))
    assert any(item["lock_type"] == "volatility_shock_lock" for item in toxic_assessment.active_risk_locks)

    integrity_assessment = asyncio.run(assess_for(FakePhase2MarketDataService(missing_funding=True)))
    assert any(item["lock_type"] == "basis_data_integrity_lock" for item in integrity_assessment.active_risk_locks)

    anomaly_assessment = asyncio.run(assess_for(FakePhase2MarketDataService(), seed_bad_exec=True))
    assert any(item["lock_type"] == "execution_anomaly_lock" for item in anomaly_assessment.active_risk_locks)


def test_liquidity_lock_allows_spread_exactly_at_configured_limit() -> None:
    class BoundarySpreadMarketDataService(FakePhase2MarketDataService):
        async def get_order_book(self, symbol: str) -> OrderBookSnapshot:
            book = await super().get_order_book(symbol)
            midpoint = self.spot_5m[-1].close
            half_spread = midpoint * (4.0 / 20000.0)
            book.bids[0] = OrderBookLevel(price=midpoint - half_spread, quantity=2.0)
            book.asks[0] = OrderBookLevel(price=midpoint + half_spread, quantity=2.0)
            return book

    settings = _settings(
        microstructure_max_relative_spread_bps=4.0,
        enable_stale_data_lock=False,
        enable_volatility_shock_lock=False,
        enable_execution_anomaly_lock=False,
        enable_basis_data_integrity_lock=False,
    )
    market_data = BoundarySpreadMarketDataService()
    risk_service = RiskService(
        settings=settings,
        market_data_service=market_data,
        time_provider=lambda: market_data.now,
        risk_lock_manager=RiskLockManager(time_provider=lambda: market_data.now),
    )

    assessment = asyncio.run(risk_service.validate_signal_payload(_candidate_payload(market_data.now)))

    assert not any(item["lock_type"] == "liquidity_thin_lock" for item in assessment.active_risk_locks)


def test_risk_lock_manager_uses_injected_replay_clock() -> None:
    replay_now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    manager = RiskLockManager(time_provider=lambda: replay_now)

    activated = manager.activate(
        lock_type="stale_data_lock",
        scope="symbol",
        scope_key="BTCUSDT",
        severity="high",
        reason="test",
    )
    cleared = manager.clear(
        lock_type="stale_data_lock",
        scope="symbol",
        scope_key="BTCUSDT",
        reason="condition_cleared",
    )

    assert activated.triggered_at == replay_now
    assert cleared is not None
    assert cleared.released_at == replay_now


def test_phase2_replay_outputs_artifacts_and_fidelity_notes() -> None:
    settings = _settings(signals_trigger_timeframe="5m")
    replay = ReplayService(settings=settings)
    end_time = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    base_1h = end_time - timedelta(hours=39)
    base_5m = end_time - timedelta(minutes=5 * 59)
    payload = {
        "BTCUSDT": {
            "1h": _make_candles(count=40, start_price=67000.0, step=24.0, start_time=base_1h, minutes=60),
            "5m": _make_candles(count=60, start_price=68400.0, step=3.0, start_time=base_5m, minutes=5),
        }
    }
    futures_payload = {
        "BTCUSDT": {
            "1h": _make_candles(
                count=40,
                start_price=67000.0,
                step=24.0,
                start_time=base_1h,
                minutes=60,
                premium_bps=18.0,
            )
        }
    }

    run = asyncio.run(
        replay.run_replay(
            candles_source=payload,
            futures_candles_source=futures_payload,
            symbols=["BTCUSDT"],
            initial_balance=100000.0,
        )
    )

    assert run.metrics is not None
    assert run.phase2_artifacts["summary"]["basis_opportunity_count"] > 0
    assert run.phase2_artifacts["summary"]["microstructure_snapshot_count"] > 0
    assert "active_risk_locks_at_end" in run.phase2_artifacts
    assert "active_risk_lock_count_at_end" in run.phase2_artifacts["summary"]
    assert len(run.fidelity_notes) >= 3


def _make_phase2_app(tmp_path: Path) -> FastAPI:
    settings = _settings(persistence_db_url=f"sqlite:///{tmp_path / 'phase2_crypto.db'}")
    engine = get_persistence_engine(settings.persistence_db_url)
    PersistenceBase.metadata.create_all(bind=engine)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    events_repo = EventsRepository(session_factory)
    feature_repo = FeatureRunsRepository(session_factory)
    regime_repo = RegimeRepository(session_factory)
    source_repo = AlphaSourcesRepository(session_factory)
    fused_repo = FusedOpportunitiesRepository(session_factory)
    legacy_alpha_repo = AlphaFusionRepository(session_factory)
    arbitrage_repo = ArbitrageRepository(session_factory)
    micro_repo = MicrostructureRepository(session_factory)
    execution_quality_repo = ExecutionQualityRepository(session_factory)
    risk_lock_repo = RiskLockEventsRepository(session_factory)
    market_data = FakePhase2MarketDataService()
    feature_service = FeatureService(
        settings=settings,
        market_data_service=market_data,
        feature_runs_repo=feature_repo,
        events_repo=events_repo,
    )
    regime_service = RegimeService(
        settings=settings,
        feature_service=feature_service,
        regime_repo=regime_repo,
        events_repo=events_repo,
    )
    execution_quality_service = ExecutionQualityService(
        settings=settings,
        repo=execution_quality_repo,
        events_repo=events_repo,
    )
    arbitrage_service = BasisFundingService(
        settings=settings,
        market_data_service=market_data,
        arbitrage_repo=arbitrage_repo,
        source_repo=source_repo,
        events_repo=events_repo,
        time_provider=lambda: market_data.now,
    )
    microstructure_service = MicrostructureService(
        settings=settings,
        market_data_service=market_data,
        repo=micro_repo,
        source_repo=source_repo,
        events_repo=events_repo,
        time_provider=lambda: market_data.now,
    )
    risk_service = RiskService(
        settings=settings,
        market_data_service=market_data,
        time_provider=lambda: market_data.now,
        risk_lock_manager=RiskLockManager(repo=risk_lock_repo, events_repo=events_repo),
        execution_quality_service=execution_quality_service,
        arbitrage_service=arbitrage_service,
        microstructure_service=microstructure_service,
        events_repo=events_repo,
    )
    alpha_service = AlphaFusionService(
        settings=settings,
        market_data_service=market_data,
        feature_service=feature_service,
        regime_service=regime_service,
        feature_runs_repo=feature_repo,
        source_repo=source_repo,
        fused_repo=fused_repo,
        fusion_repo=legacy_alpha_repo,
        regime_repo=regime_repo,
        events_repo=events_repo,
        arbitrage_service=arbitrage_service,
        microstructure_service=microstructure_service,
        risk_service=risk_service,
    )

    asyncio.run(arbitrage_service.evaluate_symbol("BTCUSDT"))
    asyncio.run(microstructure_service.compute_symbol("BTCUSDT"))
    asyncio.run(alpha_service.evaluate_symbols(["BTCUSDT"]))
    risk_assessment = asyncio.run(risk_service.validate_signal_payload(_candidate_payload(market_data.now)))
    snapshot = asyncio.run(market_data.get_snapshot("BTCUSDT"))
    execution_quality_service.record_execution(
        trade=_make_trade(market_data.now, trade_id="api_trade", fill_price=68850.0),
        approval=_make_approval(market_data.now, trade_id="api_trade"),
        assessment=risk_assessment,
        snapshot=snapshot,
        mode="paper",
        execution_policy="simulation_only",
        partial_fill_ratio=0.7,
    )

    app = FastAPI()
    app.include_router(alpha_router, prefix="/api/v1")
    app.include_router(arbitrage_router, prefix="/api/v1")
    app.include_router(microstructure_router, prefix="/api/v1")
    app.include_router(execution_quality_router, prefix="/api/v1")
    app.include_router(risk_router, prefix="/api/v1")
    app.include_router(system_router, prefix="/api/v1")
    app.state.alpha_fusion_service = alpha_service
    app.state.arbitrage_service = arbitrage_service
    app.state.microstructure_service = microstructure_service
    app.state.execution_quality_service = execution_quality_service
    app.state.risk_service = risk_service
    return app


def test_phase2_api_endpoints_return_expected_payloads(tmp_path: Path) -> None:
    app = _make_phase2_app(tmp_path)

    with TestClient(app) as client:
        arbitrage_response = client.get("/api/v1/arbitrage/opportunities", params={"symbol": "BTCUSDT", "tradable": True})
        alpha_response = client.get("/api/v1/alpha/sources", params={"source": "binance_microstructure"})
        micro_response = client.get("/api/v1/microstructure/current", params={"symbol": "BTCUSDT"})
        execution_quality_response = client.get("/api/v1/execution/quality", params={"symbol": "BTCUSDT"})
        risk_locks_response = client.get("/api/v1/risk/locks/history")
        summary_response = client.get("/api/v1/system/intelligence/summary")

    assert arbitrage_response.status_code == 200
    assert arbitrage_response.json()["count"] >= 1
    assert arbitrage_response.json()["items"][0]["signal_family"] == "basis_funding"

    assert alpha_response.status_code == 200
    assert any(item["source_name"] == "binance_microstructure" for item in alpha_response.json()["items"])

    assert micro_response.status_code == 200
    assert micro_response.json()["count"] == 1

    assert execution_quality_response.status_code == 200
    assert execution_quality_response.json()["count"] >= 1

    assert risk_locks_response.status_code == 200
    assert risk_locks_response.json()["count"] >= 0

    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert "basis_funding_highlights" in summary_payload
    assert "microstructure_status" in summary_payload
    assert "tradability_state" in summary_payload

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.openclaw_bridge import OpenClawBridge
from app.alpha_fusion.service import AlphaFusionService
from app.api.routes.alpha import router as alpha_router
from app.api.routes.arbitrage import router as arbitrage_router
from app.api.routes.events import router as events_router
from app.api.routes.execution_quality import router as execution_quality_router
from app.api.routes.mirofish import router as mirofish_router
from app.api.routes.polymarket import router as polymarket_router
from app.api.routes.portfolio_brain import router as portfolio_brain_router
from app.api.routes.promotion import router as promotion_router
from app.api.routes.provider_health import router as provider_health_router
from app.api.routes.risk import router as risk_router
from app.api.routes.system_intelligence import router as system_router
from app.api.routes.system_records import router as system_records_router
from app.api.routes.wallets import router as wallets_router
from app.arbitrage.service import BasisFundingService
from app.config.settings import get_settings
from app.event_signals.service import EventSignalsService
from app.execution.types import Approval, Trade
from app.execution_quality.service import ExecutionQualityService
from app.market_data.types import TickerSnapshot
from app.persistence.db import get_persistence_engine, get_persistence_session_factory
from app.persistence.models import PersistenceBase
from app.persistence.repositories.alpha_fusion_repo import AlphaFusionRepository
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.execution_quality_repo import ExecutionQualityRepository
from app.persistence.repositories.fused_opportunities_repo import FusedOpportunitiesRepository
from app.persistence.repositories.mirofish_repo import MiroFishRepository
from app.persistence.repositories.polymarket_repo import PolymarketRepository
from app.persistence.repositories.portfolio_brain_repo import PortfolioBrainRepository
from app.persistence.repositories.promotion_repo import PromotionRepository
from app.persistence.repositories.provider_health_repo import ProviderHealthRepository
from app.persistence.repositories.risk_lock_events_repo import RiskLockEventsRepository
from app.persistence.repositories.system_records_repo import SystemRecordsRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.persistence.repositories.wallet_repo import WalletRepository
from app.persistence.repositories.event_signals_repo import EventSignalsRepository
from app.polymarket.service import PolymarketService
from app.portfolio_brain.service import PortfolioBrainService
from app.promotion.service import PromotionService
from app.provider_health.service import ProviderHealthService
from app.risk.locks import RiskLockManager
from app.risk.service import RiskService
from app.simulation.mirofish_adapter import MiroFishAdapter
from app.wallet_intel.service import WalletIntelService


def _phase3_settings(tmp_path: Path, **updates: object):
    defaults = {
        "persistence_db_url": f"sqlite:///{tmp_path / 'phase3_platform.db'}",
        "signals_supported_symbols": ["BTCUSDT"],
        "polymarket_provider": "mock",
        "wallet_provider": "mock",
        "event_provider": "mock",
        "enable_polymarket_engine": True,
        "enable_wallet_intel": True,
        "enable_event_signals": True,
        "enable_mirofish": True,
        "mirofish_provider": "mock",
        "enable_openclaw_bridge": True,
        "openclaw_dry_run": True,
        "enable_provider_health": True,
        "enable_provider_health_veto": True,
        "polymarket_min_net_edge_bps": 1.0,
        "polymarket_min_depth_usd": 1000.0,
        "polymarket_max_data_age_seconds": 120,
        "wallet_min_quality_score": 0.55,
        "wallet_max_crowding_score": 0.8,
        "wallet_signal_mode": "hybrid",
        "event_min_importance_score": 0.5,
        "event_min_relevance_score": 0.5,
        "fusion_weight_polymarket": 0.4,
        "fusion_weight_wallet": 0.2,
        "fusion_weight_event": 0.25,
        "fusion_weight_mirofish": 0.15,
        "alpha_long_threshold": 0.54,
        "alpha_short_threshold": 0.54,
        "enable_portfolio_brain": True,
        "portfolio_max_strategy_weight": 0.6,
        "portfolio_max_market_weight": 0.5,
        "enable_promotion_ladder": True,
        "promotion_min_sample_count": 1,
        "promotion_min_expectancy": 0.0,
        "promotion_max_drawdown": 100.0,
        "promotion_min_execution_quality": 0.5,
        "promotion_min_provider_health": 0.5,
        "execution_quality_bad_score_threshold": 0.45,
        "microstructure_max_relative_spread_bps": 5.0,
    }
    defaults.update(updates)
    return get_settings().model_copy(update=defaults)


def _build_trade(now: datetime, *, trade_id: str, strategy_name: str, realized_pnl: float = 0.0) -> Trade:
    return Trade(
        trade_id=trade_id,
        approval_id=f"apr_{trade_id}",
        assessment_id=f"asm_{trade_id}",
        signal_id=f"sig_{trade_id}",
        position_id=f"pos_{trade_id}",
        symbol="BTCUSDT",
        side="long",
        strategy_name=strategy_name,
        quantity=0.25,
        execution_price=68520.0,
        requested_entry_price=68500.0,
        stop_loss=68150.0,
        target_1=69000.0,
        target_2=69400.0,
        status="open",
        execution_mode="paper",
        opened_at=now,
        updated_at=now,
        realized_pnl=realized_pnl,
    )


def _build_approval(now: datetime, *, trade_id: str, strategy_name: str) -> Approval:
    return Approval(
        approval_id=f"apr_{trade_id}",
        assessment_id=f"asm_{trade_id}",
        signal_id=f"sig_{trade_id}",
        symbol="BTCUSDT",
        side="long",
        strategy_name=strategy_name,
        status="approved",
        created_at=now - timedelta(seconds=3),
        approved_at=now - timedelta(seconds=2),
    )


def _build_phase3_stack(tmp_path: Path):
    settings = _phase3_settings(tmp_path)
    engine = get_persistence_engine(settings.persistence_db_url)
    PersistenceBase.metadata.create_all(bind=engine)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)

    events_repo = EventsRepository(session_factory)
    source_repo = AlphaSourcesRepository(session_factory)
    fused_repo = FusedOpportunitiesRepository(session_factory)
    legacy_fusion_repo = AlphaFusionRepository(session_factory)
    polymarket_repo = PolymarketRepository(session_factory)
    wallet_repo = WalletRepository(session_factory)
    event_repo = EventSignalsRepository(session_factory)
    provider_health_repo = ProviderHealthRepository(session_factory)
    portfolio_repo = PortfolioBrainRepository(session_factory)
    promotion_repo = PromotionRepository(session_factory)
    system_records_repo = SystemRecordsRepository(session_factory)
    mirofish_repo = MiroFishRepository(session_factory)
    execution_quality_repo = ExecutionQualityRepository(session_factory)
    trades_repo = TradesRepository(session_factory)
    risk_lock_repo = RiskLockEventsRepository(session_factory)

    polymarket_service = PolymarketService(
        settings=settings,
        repo=polymarket_repo,
        source_repo=source_repo,
        events_repo=events_repo,
    )
    wallet_service = WalletIntelService(
        settings=settings,
        repo=wallet_repo,
        source_repo=source_repo,
        events_repo=events_repo,
    )
    wallet_service.provider._wallets["wal_alpha"]["trades"].append(
        {
            "market": "pm_crypto_etf_approval",
            "action": "buy_yes",
            "timestamp": datetime(2026, 4, 8, 11, 0, tzinfo=timezone.utc),
            "conviction": 0.88,
            "size": "medium",
        }
    )
    event_service = EventSignalsService(
        settings=settings,
        repo=event_repo,
        source_repo=source_repo,
        events_repo=events_repo,
    )
    provider_health_service = ProviderHealthService(
        settings=settings,
        repo=provider_health_repo,
        events_repo=events_repo,
    )
    mirofish_adapter = MiroFishAdapter(
        settings=settings,
        repo=mirofish_repo,
        source_repo=source_repo,
        events_repo=events_repo,
    )
    execution_quality_service = ExecutionQualityService(
        settings=settings,
        repo=execution_quality_repo,
        events_repo=events_repo,
    )
    promotion_service = PromotionService(
        settings=settings,
        execution_quality_service=execution_quality_service,
        trades_repo=trades_repo,
        provider_health_service=provider_health_service,
        events_repo=events_repo,
        repo=promotion_repo,
    )
    basis_service = BasisFundingService(settings=settings)
    risk_lock_manager = RiskLockManager(repo=risk_lock_repo, events_repo=events_repo)
    risk_service = RiskService(
        settings=settings,
        risk_lock_manager=risk_lock_manager,
        execution_quality_service=execution_quality_service,
        arbitrage_service=basis_service,
        events_repo=events_repo,
    )
    alpha_service = AlphaFusionService(
        settings=settings,
        source_repo=source_repo,
        fused_repo=fused_repo,
        fusion_repo=legacy_fusion_repo,
        events_repo=events_repo,
        arbitrage_service=basis_service,
        polymarket_service=polymarket_service,
        wallet_intel_service=wallet_service,
        event_signals_service=event_service,
        provider_health_service=provider_health_service,
        mirofish_adapter=mirofish_adapter,
        risk_service=risk_service,
    )
    portfolio_service = PortfolioBrainService(
        settings=settings,
        alpha_fusion_service=alpha_service,
        risk_service=risk_service,
        provider_health_service=provider_health_service,
        promotion_service=promotion_service,
        repo=portfolio_repo,
        events_repo=events_repo,
    )
    openclaw_bridge = OpenClawBridge(
        settings=settings,
        repo=system_records_repo,
        events_repo=events_repo,
    )

    asyncio.run(polymarket_service.refresh())
    asyncio.run(wallet_service.refresh())
    asyncio.run(event_service.refresh())
    asyncio.run(
        provider_health_service.evaluate_all(
            {
                "polymarket": polymarket_service.provider,
                "wallet_intel": wallet_service.provider,
                "event_signals": event_service.provider,
                "mirofish": mirofish_adapter,
                "openclaw": openclaw_bridge,
            }
        )
    )
    return {
        "settings": settings,
        "polymarket_service": polymarket_service,
        "wallet_service": wallet_service,
        "event_service": event_service,
        "provider_health_service": provider_health_service,
        "mirofish_adapter": mirofish_adapter,
        "execution_quality_service": execution_quality_service,
        "promotion_service": promotion_service,
        "basis_service": basis_service,
        "risk_lock_manager": risk_lock_manager,
        "risk_service": risk_service,
        "alpha_service": alpha_service,
        "portfolio_service": portfolio_service,
        "openclaw_bridge": openclaw_bridge,
        "trades_repo": trades_repo,
    }


def _build_phase3_app(tmp_path: Path) -> FastAPI:
    stack = _build_phase3_stack(tmp_path)
    app = FastAPI()
    app.include_router(alpha_router, prefix="/api/v1")
    app.include_router(arbitrage_router, prefix="/api/v1")
    app.include_router(polymarket_router, prefix="/api/v1")
    app.include_router(wallets_router, prefix="/api/v1")
    app.include_router(events_router, prefix="/api/v1")
    app.include_router(provider_health_router, prefix="/api/v1")
    app.include_router(portfolio_brain_router, prefix="/api/v1")
    app.include_router(promotion_router, prefix="/api/v1")
    app.include_router(system_router, prefix="/api/v1")
    app.include_router(system_records_router, prefix="/api/v1")
    app.include_router(mirofish_router, prefix="/api/v1")
    app.include_router(execution_quality_router, prefix="/api/v1")
    app.include_router(risk_router, prefix="/api/v1")
    app.state.alpha_fusion_service = stack["alpha_service"]
    app.state.arbitrage_service = stack["basis_service"]
    app.state.polymarket_service = stack["polymarket_service"]
    app.state.wallet_intel_service = stack["wallet_service"]
    app.state.event_signals_service = stack["event_service"]
    app.state.provider_health_service = stack["provider_health_service"]
    app.state.portfolio_brain_service = stack["portfolio_service"]
    app.state.promotion_service = stack["promotion_service"]
    app.state.openclaw_bridge = stack["openclaw_bridge"]
    app.state.mirofish_adapter = stack["mirofish_adapter"]
    app.state.execution_quality_service = stack["execution_quality_service"]
    app.state.risk_service = stack["risk_service"]
    app.state._phase3_stack = stack
    return app


def test_polymarket_engine_detects_dislocations_and_stale_markets(tmp_path: Path) -> None:
    stack = _build_phase3_stack(tmp_path)
    service = stack["polymarket_service"]

    opportunities = asyncio.run(service.evaluate_opportunities())
    types = {item.opportunity_type for item in opportunities}

    assert "yes_no_sum_dislocation" in types
    assert "linked_market_inconsistency" in types
    assert any(item.tradable for item in opportunities if item.opportunity_type == "yes_no_sum_dislocation")

    service.provider._markets["pm_us_election_yes"].last_updated_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    stale_opportunities = asyncio.run(service.evaluate_opportunities())
    stale_item = next(item for item in stale_opportunities if item.market_id == "pm_us_election_yes")
    assert stale_item.stale_market is True
    assert stale_item.tradable is False


def test_wallet_intelligence_scores_leaderboards_and_signal_modes(tmp_path: Path) -> None:
    stack = _build_phase3_stack(tmp_path)
    service = stack["wallet_service"]

    wallets = asyncio.run(service.list_wallets())
    signals = service.list_signals(limit=10)
    crowded = service.leaderboard(mode="crowded", limit=2)

    assert len(wallets) >= 2
    assert crowded[0].crowding_score >= crowded[1].crowding_score
    assert any(item.recommended_action == "follow" for item in signals)
    assert any(item.recommended_action == "fade" for item in signals)
    assert all(0.0 <= item.quality_score <= 1.0 for item in wallets)


def test_event_framework_normalizes_decays_and_classifies_windows(tmp_path: Path) -> None:
    stack = _build_phase3_stack(tmp_path)
    service = stack["event_service"]

    events = asyncio.run(service.list_events())
    signals = service.list_signals(limit=10)
    pre_event = next(item for item in events if item.event_id == "evt_fed_hold")
    recent = next(item for item in events if item.event_id == "evt_crypto_etf")

    assert pre_event.event_window_state == "pre_event"
    assert recent.event_window_state in {"during_event", "post_event"}
    assert 0.0 < service.decay(recent) <= 1.0
    assert service.classify_event_window(datetime.now(timezone.utc) - timedelta(hours=8)) == "stale_event"
    assert any(item.symbol_or_market == "pm_crypto_etf_approval" for item in signals)


def test_alpha_fusion_phase3_uses_multi_source_inputs_and_provider_health_veto(tmp_path: Path) -> None:
    stack = _build_phase3_stack(tmp_path)
    alpha_service = stack["alpha_service"]
    provider_health_service = stack["provider_health_service"]

    signals = asyncio.run(alpha_service.evaluate_targets(["pm_crypto_etf_approval"]))
    signal = signals[0]
    assert signal.strategy_family == "prediction_market_phase3"
    assert "polymarket_mispricing" in signal.source_breakdown
    assert "event_signals" in signal.source_breakdown
    assert "mirofish_simulation" in signal.source_breakdown
    assert "provider_unhealthy_veto" not in signal.veto_factors

    class BrokenProvider:
        async def health_check(self) -> dict[str, object]:
            return {"status": "unhealthy", "success_rate": 0.0, "stale_data_flag": True, "error_count": 5}

    asyncio.run(provider_health_service.evaluate_provider("wallet_intel", BrokenProvider()))
    vetoed = asyncio.run(alpha_service.evaluate_targets(["pm_crypto_etf_approval"]))[0]
    assert "provider_unhealthy_veto" in vetoed.veto_factors
    assert vetoed.tradable is False


def test_portfolio_brain_promotion_provider_health_openclaw_and_mirofish_integrate(tmp_path: Path) -> None:
    stack = _build_phase3_stack(tmp_path)
    alpha_service = stack["alpha_service"]
    portfolio_service = stack["portfolio_service"]
    promotion_service = stack["promotion_service"]
    execution_quality_service = stack["execution_quality_service"]
    trades_repo = stack["trades_repo"]
    openclaw_bridge = stack["openclaw_bridge"]
    mirofish_adapter = stack["mirofish_adapter"]
    risk_lock_manager = stack["risk_lock_manager"]

    asyncio.run(alpha_service.evaluate_targets(["pm_crypto_etf_approval"]))
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    trade = _build_trade(now, trade_id="trade_phase3", strategy_name="prediction_market_phase3", realized_pnl=120.0)
    approval = _build_approval(now, trade_id="trade_phase3", strategy_name="prediction_market_phase3")
    trades_repo.upsert_trade(trade)
    execution_quality_service.record_execution(
        trade=trade,
        approval=approval,
        assessment=None,
        snapshot=TickerSnapshot(
            symbol="BTCUSDT",
            last_price=68510.0,
            bid_price=68505.0,
            ask_price=68515.0,
            spread_bps=1.5,
            snapshot_time=now,
        ),
        mode="paper",
        execution_policy="maker_preferred",
        fill_timestamp=now,
    )
    status = promotion_service.evaluate_strategy_for_promotion("prediction_market_phase3")
    review = promotion_service.record_review("prediction_market_phase3")
    scenario = mirofish_adapter.run(symbol_or_market="pm_crypto_etf_approval", payload={"event_bias": 0.6, "wallet_bias": 0.3, "polymarket_bias": 0.5})
    risk_lock_manager.activate(
        lock_type="provider_health_lock",
        scope="system",
        scope_key="global",
        severity="medium",
        reason="degraded_provider_mix",
        metrics_snapshot={"affected": 1},
    )
    snapshot = portfolio_service.generate_recommendations(execution_mode="paper")
    alert = openclaw_bridge.create_alert(
        opportunity_id="alpha_phase3_signal",
        strategy_family="prediction_market_phase3",
        summary="Phase 3 opportunity requires operator review.",
        severity="high",
    )
    approval_payload = openclaw_bridge.create_approval_request(opportunity=review, promotion_status=status)

    assert status.eligible_for_promotion is True
    assert review.decision in {"promote", "hold"}
    assert snapshot.capital_by_strategy_family
    assert snapshot.gross_exposure_cap < 1.0
    assert alert["dry_run"] is True
    assert approval_payload["requires_human_approval"] is True
    assert scenario.scenario_confidence > 0.0
    assert mirofish_adapter.as_source_reading(scenario).source_name == "mirofish_simulation"


def test_phase3_api_endpoints_return_stable_payloads(tmp_path: Path) -> None:
    app = _build_phase3_app(tmp_path)
    stack = app.state._phase3_stack
    alpha_service = stack["alpha_service"]
    portfolio_service = stack["portfolio_service"]
    promotion_service = stack["promotion_service"]
    execution_quality_service = stack["execution_quality_service"]
    trades_repo = stack["trades_repo"]
    openclaw_bridge = stack["openclaw_bridge"]
    risk_lock_manager = stack["risk_lock_manager"]

    asyncio.run(alpha_service.evaluate_targets(["pm_crypto_etf_approval"]))
    portfolio_service.generate_recommendations(execution_mode="paper")
    now = datetime(2026, 4, 8, 12, 30, tzinfo=timezone.utc)
    trade = _build_trade(now, trade_id="trade_api_phase3", strategy_name="prediction_market_phase3", realized_pnl=75.0)
    approval = _build_approval(now, trade_id="trade_api_phase3", strategy_name="prediction_market_phase3")
    trades_repo.upsert_trade(trade)
    execution_quality_service.record_execution(
        trade=trade,
        approval=approval,
        assessment=None,
        snapshot=TickerSnapshot(
            symbol="BTCUSDT",
            last_price=68500.0,
            bid_price=68495.0,
            ask_price=68505.0,
            spread_bps=1.6,
            snapshot_time=now,
        ),
        mode="paper",
        execution_policy="maker_preferred",
        fill_timestamp=now,
    )
    promotion_service.record_review("prediction_market_phase3")
    openclaw_bridge.create_alert(
        opportunity_id="pm_crypto_etf_approval",
        strategy_family="prediction_market_phase3",
        summary="Prediction market opportunity surfaced.",
        severity="medium",
    )
    openclaw_bridge.add_operator_note(related_entity_id="pm_crypto_etf_approval", note="Paper only until next review.")
    openclaw_bridge.log_incident(severity="low", title="Mock provider latency spike", related_entity_id="event_signals")
    stack["mirofish_adapter"].run(symbol_or_market="pm_crypto_etf_approval", payload={"event_bias": 0.4, "polymarket_bias": 0.5})
    risk_lock_manager.activate(
        lock_type="execution_anomaly_lock",
        scope="system",
        scope_key="global",
        severity="critical",
        reason="synthetic_test_lock",
        metrics_snapshot={"bad_record_count": 3},
    )

    with TestClient(app) as client:
        responses = {
            "polymarket_markets": client.get("/api/v1/polymarket/markets"),
            "polymarket_opportunities": client.get("/api/v1/polymarket/opportunities"),
            "wallets_leaderboard": client.get("/api/v1/wallets/leaderboard"),
            "wallet_signals": client.get("/api/v1/wallets/signals"),
            "events_signals": client.get("/api/v1/events/signals"),
            "provider_health_summary": client.get("/api/v1/provider-health/summary"),
            "alpha_fused": client.post("/api/v1/alpha/fused", json={"targets": ["pm_crypto_etf_approval"]}),
            "alpha_sources": client.get("/api/v1/alpha/sources", params={"source": "polymarket_mispricing"}),
            "portfolio_brain": client.get("/api/v1/portfolio/brain"),
            "promotion_status": client.get("/api/v1/promotion/status"),
            "system_operator_notes": client.get("/api/v1/system/operator-notes"),
            "system_incidents": client.get("/api/v1/system/incidents"),
            "system_alerts": client.get("/api/v1/system/alerts/history"),
            "mirofish_latest": client.get("/api/v1/simulation/mirofish/latest"),
            "execution_quality": client.get("/api/v1/execution/quality"),
            "risk_locks": client.get("/api/v1/risk/locks/current"),
            "system_summary": client.get("/api/v1/system/intelligence/summary"),
            "arbitrage_opportunities": client.get("/api/v1/arbitrage/opportunities"),
        }

    for name, response in responses.items():
        assert response.status_code == 200, (name, response.text)

    assert responses["wallets_leaderboard"].json()["count"] >= 1
    assert responses["events_signals"].json()["count"] >= 1
    assert responses["provider_health_summary"].json()["count"] >= 4
    assert responses["alpha_fused"].json()["count"] == 1
    assert responses["execution_quality"].json()["count"] >= 1
    assert responses["risk_locks"].json()["count"] >= 1
    assert responses["system_summary"].json()["provider_health"]["count"] >= 4
    assert responses["arbitrage_opportunities"].json()["count"] >= 1

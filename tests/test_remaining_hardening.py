from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.openclaw_bridge import OpenClawBridge
from app.api.routes.replay import router as replay_router
from app.api.routes.research import router as research_router
from app.api.routes.system_records import router as system_records_router
from app.config.settings import Settings, get_settings
from app.event_signals.providers import FallbackEventProvider, MockEventProvider, RealEventProvider
from app.event_signals.service import EventSignalsService
from app.persistence.db import get_persistence_engine, get_persistence_session_factory
from app.persistence.models import PersistenceBase
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.event_signals_repo import EventSignalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.polymarket_repo import PolymarketRepository
from app.persistence.repositories.portfolio_brain_repo import PortfolioBrainRepository
from app.persistence.repositories.provider_health_repo import ProviderHealthRepository
from app.persistence.repositories.replay_repo import ReplayRepository
from app.persistence.repositories.research_repo import ResearchRepository
from app.persistence.repositories.system_records_repo import SystemRecordsRepository
from app.persistence.repositories.wallet_repo import WalletRepository
from app.polymarket.providers import RealPolymarketProvider
from app.polymarket.service import PolymarketService
from app.portfolio_brain.service import PortfolioBrainService
from app.provider_health.service import ProviderHealthService
from app.replay.service import ReplayService
from app.research.service import ResearchService
from app.wallet_intel.providers import FallbackWalletProvider, MockWalletProvider, RealWalletProvider
from app.wallet_intel.service import WalletIntelService


def _settings(tmp_path: Path, **updates: object):
    defaults = {
        "persistence_db_url": f"sqlite:///{tmp_path / 'remaining_hardening.db'}",
        "polymarket_provider_mode": "mock",
        "wallet_provider_mode": "mock",
        "event_provider_mode": "mock",
        "enable_backfill_jobs": True,
        "replay_default_fidelity": "medium",
        "signals_supported_symbols": ["BTCUSDT"],
    }
    defaults.update(updates)
    return get_settings().model_copy(update=defaults)


def test_settings_sync_legacy_provider_fields_to_modes() -> None:
    settings = Settings.model_validate(
        {
            "polymarket_provider": "real",
            "wallet_provider_mode": "auto_fallback",
            "event_provider": "real",
        }
    )
    assert settings.polymarket_provider == "real"
    assert settings.polymarket_provider_mode == "real"
    assert settings.wallet_provider == "auto_fallback"
    assert settings.wallet_provider_mode == "auto_fallback"
    assert settings.event_provider == "real"
    assert settings.event_provider_mode == "real"


def test_settings_accept_empty_event_news_feed_urls_from_env(monkeypatch) -> None:
    monkeypatch.setenv("EVENT_NEWS_FEED_URLS", "")

    settings = Settings(_env_file=None)

    assert settings.event_news_feed_urls == []


def _build_storage(tmp_path: Path):
    settings = _settings(tmp_path)
    engine = get_persistence_engine(settings.persistence_db_url)
    PersistenceBase.metadata.create_all(bind=engine)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    return settings, session_factory


def test_real_polymarket_provider_normalizes_public_payloads() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/markets":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "1",
                            "slug": "pm_btc_etf",
                            "question": "Will BTC ETF be approved?",
                            "category": "crypto",
                            "eventSlug": "btc-etf",
                            "yesPrice": "0.62",
                            "updatedAt": "2026-04-08T10:00:00Z",
                            "status": "open",
                        }
                    ],
                )
            if request.url.path == "/v1/markets/pm_btc_etf/book":
                return httpx.Response(
                    200,
                    json={
                        "bids": [{"price": "0.61", "size": "5000"}],
                        "asks": [{"price": "0.63", "size": "4500"}],
                        "marketSlug": "pm_btc_etf",
                        "transactTime": "2026-04-08T10:01:00Z",
                    },
                )
            raise AssertionError(request.url.path)

        settings = _settings(Path("/tmp"), polymarket_base_url="https://example.test", polymarket_timeout_ms=1000)
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(base_url="https://example.test", transport=transport) as client:
            provider = RealPolymarketProvider(settings=settings, client=client)
            markets = await provider.list_markets()
            orderbook = await provider.get_orderbook("pm_btc_etf")
            health = await provider.health_check()

        assert markets[0].market_id == "pm_btc_etf"
        assert markets[0].yes_price == 0.62
        assert markets[0].no_price == 0.38
        assert orderbook is not None
        assert orderbook.depth_usd > 0
        assert health["status"] in {"healthy", "degraded"}

    asyncio.run(run())


def test_wallet_and_event_fallback_providers_preserve_mock_mode_on_real_failure() -> None:
    async def run() -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "down"})

        transport = httpx.MockTransport(handler)
        settings = _settings(Path("/tmp"), wallet_provider_base_url="https://wallet.test", app_env="development")
        async with httpx.AsyncClient(base_url="https://wallet.test", transport=transport) as wallet_client:
            wallet_provider = FallbackWalletProvider(
                real=RealWalletProvider(settings=settings, client=wallet_client),
                mock=MockWalletProvider(),
                allow_mock_fallback=True,
            )
            wallets = await wallet_provider.list_wallets()
            wallet_health = await wallet_provider.health_check()

        event_settings = _settings(Path("/tmp"), event_news_feed_urls=["https://news.test/feed.xml"], app_env="development")
        async with httpx.AsyncClient(transport=transport) as event_client:
            event_provider = FallbackEventProvider(
                real=RealEventProvider(settings=event_settings, client=event_client),
                mock=MockEventProvider(),
                allow_mock_fallback=True,
            )
            events = await event_provider.list_events()
            event_health = await event_provider.health_check()

        assert wallets
        assert wallet_health["metadata"]["fallback_active"] is True
        assert events
        assert event_health["metadata"]["fallback_active"] is True

    asyncio.run(run())


def test_configured_real_wallet_provider_does_not_fallback_on_legit_empty_dataset() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/wallets":
                return httpx.Response(200, json={"wallets": []})
            raise AssertionError(request.url.path)

        transport = httpx.MockTransport(handler)
        settings = _settings(Path("/tmp"), wallet_provider_base_url="https://wallet.test", app_env="development")
        async with httpx.AsyncClient(base_url="https://wallet.test", transport=transport) as wallet_client:
            provider = FallbackWalletProvider(
                real=RealWalletProvider(settings=settings, client=wallet_client),
                mock=MockWalletProvider(),
                allow_mock_fallback=True,
            )
            wallets = await provider.list_wallets()
            health = await provider.health_check()

        assert wallets == []
        assert health["metadata"]["fallback_active"] is False

    asyncio.run(run())


def test_replay_fidelity_and_backfill_jobs_are_persisted_and_idempotent(tmp_path: Path) -> None:
    settings, session_factory = _build_storage(tmp_path)
    events_repo = EventsRepository(session_factory)
    source_repo = AlphaSourcesRepository(session_factory)
    polymarket_repo = PolymarketRepository(session_factory)
    wallet_repo = WalletRepository(session_factory)
    event_repo = EventSignalsRepository(session_factory)
    provider_health_repo = ProviderHealthRepository(session_factory)
    research_repo = ResearchRepository(session_factory)
    replay_repo = ReplayRepository(session_factory)

    provider_health_service = ProviderHealthService(settings=settings, repo=provider_health_repo, events_repo=events_repo)
    polymarket_service = PolymarketService(
        settings=settings,
        repo=polymarket_repo,
        source_repo=source_repo,
        events_repo=events_repo,
        provider_health_service=provider_health_service,
    )
    wallet_service = WalletIntelService(
        settings=settings,
        repo=wallet_repo,
        source_repo=source_repo,
        events_repo=events_repo,
        provider_health_service=provider_health_service,
    )
    event_service = EventSignalsService(
        settings=settings,
        repo=event_repo,
        source_repo=source_repo,
        events_repo=events_repo,
        provider_health_service=provider_health_service,
    )
    research_service = ResearchService(
        settings=settings,
        research_repo=research_repo,
        polymarket_service=polymarket_service,
        wallet_intel_service=wallet_service,
        event_signals_service=event_service,
        provider_health_service=provider_health_service,
    )
    replay_service = ReplayService(settings=settings, replay_repo=replay_repo)

    job = asyncio.run(research_service.run_backfill_job(dataset_type="polymarket_markets", provider_name="polymarket"))
    rerun = asyncio.run(research_service.run_backfill_job(dataset_type="polymarket_markets", provider_name="polymarket"))
    assert job.job_id == rerun.job_id
    assert rerun.status == "completed"

    candles = {
        "BTCUSDT": {
            "5m": [
                {
                    "open_time": datetime(2026, 4, 8, 9, 0, tzinfo=timezone.utc),
                    "open": 68000.0,
                    "high": 68120.0,
                    "low": 67980.0,
                    "close": 68100.0,
                    "volume": 120.0,
                    "is_closed": True,
                },
                {
                    "open_time": datetime(2026, 4, 8, 9, 5, tzinfo=timezone.utc),
                    "open": 68100.0,
                    "high": 68250.0,
                    "low": 68050.0,
                    "close": 68200.0,
                    "volume": 140.0,
                    "is_closed": True,
                },
            ],
            "1h": [
                {
                    "open_time": datetime(2026, 4, 8, 9, 0, tzinfo=timezone.utc),
                    "open": 68000.0,
                    "high": 68300.0,
                    "low": 67900.0,
                    "close": 68200.0,
                    "volume": 800.0,
                    "is_closed": True,
                }
            ],
        }
    }
    run = asyncio.run(
        replay_service.run_replay(
            candles_source=candles,
            futures_candles_source=candles,
            fidelity_mode="high_fidelity_best_effort",
            polymarket_snapshots=[{"market_id": "pm_btc", "yes_price": 0.62, "no_price": 0.42}],
            event_observations=[{"event_id": "evt1", "importance_score": 0.8, "relevance_score": 0.7, "entities": ["BTCUSDT"]}],
            wallet_observations=[{"wallet_id": "wal_alpha", "market": "BTCUSDT", "conviction": 0.72}],
        )
    )
    persisted = replay_repo.get_replay_run(run.run_id)
    assert persisted is not None
    assert persisted.fidelity_metadata is not None
    assert persisted.fidelity_metadata.precision_claim == "best_effort_snapshot_reconstruction"
    assert persisted.phase2_artifacts["prediction_market_replay"]["polymarket_signal_candidates"]


def test_portfolio_correlation_caps_and_incident_workflow_are_explainable(tmp_path: Path) -> None:
    settings, session_factory = _build_storage(tmp_path)
    settings = settings.model_copy(
        update={
            "portfolio_max_strategy_weight": 0.8,
            "portfolio_bucket_cap_crypto_directional": 0.4,
            "portfolio_bucket_cap_wallet_follow": 0.2,
        }
    )
    events_repo = EventsRepository(session_factory)
    portfolio_repo = PortfolioBrainRepository(session_factory)
    system_records_repo = SystemRecordsRepository(session_factory)
    bridge = OpenClawBridge(settings=settings, repo=system_records_repo, events_repo=events_repo)

    alpha_stub = SimpleNamespace(
        list_fused_signals=lambda limit=100: [
            SimpleNamespace(score=0.9, confidence=0.9, strategy_family="technical_features", symbol="BTCUSDT", veto_factors=[]),
            SimpleNamespace(score=0.8, confidence=0.8, strategy_family="binance_basis", symbol="ETHUSDT", veto_factors=[]),
            SimpleNamespace(score=0.85, confidence=0.7, strategy_family="wallet_intelligence", symbol="BTCUSDT", veto_factors=[]),
            SimpleNamespace(score=0.7, confidence=0.8, strategy_family="polymarket_mispricing", symbol="pm_event_x", veto_factors=["thin_book"]),
        ]
    )
    provider_health_stub = SimpleNamespace(build_summary=lambda: {"unhealthy": 1})
    risk_stub = SimpleNamespace(list_current_locks=lambda: [{"scope_key": "system"}])
    promotion_stub = SimpleNamespace(list_status=lambda: [])
    service = PortfolioBrainService(
        settings=settings,
        alpha_fusion_service=alpha_stub,
        risk_service=risk_stub,
        provider_health_service=provider_health_stub,
        promotion_service=promotion_stub,
        repo=portfolio_repo,
        events_repo=events_repo,
    )
    snapshot = service.generate_recommendations(execution_mode="paper")
    assert "bucket_cap_applied:" in " ".join(snapshot.explanation)
    assert snapshot.strategy_throttles
    assert snapshot.metadata["correlation_buckets"]

    incident = bridge.create_incident(
        category="provider_outage",
        severity="high",
        source="provider_health",
        impacted_scope="provider",
        title="Wallet provider unhealthy",
        related_provider="wallet_intel",
    )
    acknowledged = bridge.acknowledge_incident(incident["incident_id"], note="Investigating feed gap")
    resolved = bridge.resolve_incident(incident["incident_id"], note="Recovered after restart")
    assert acknowledged is not None and acknowledged["status"] == "acknowledged"
    assert resolved is not None and resolved["status"] == "resolved"
    assert bridge.list_operator_notes(limit=10)


def test_research_replay_and_incident_routes_remain_stable(tmp_path: Path) -> None:
    settings, session_factory = _build_storage(tmp_path)
    events_repo = EventsRepository(session_factory)
    source_repo = AlphaSourcesRepository(session_factory)
    polymarket_service = PolymarketService(
        settings=settings,
        repo=PolymarketRepository(session_factory),
        source_repo=source_repo,
        events_repo=events_repo,
    )
    wallet_service = WalletIntelService(
        settings=settings,
        repo=WalletRepository(session_factory),
        source_repo=source_repo,
        events_repo=events_repo,
    )
    event_service = EventSignalsService(
        settings=settings,
        repo=EventSignalsRepository(session_factory),
        source_repo=source_repo,
        events_repo=events_repo,
    )
    research_service = ResearchService(
        settings=settings,
        research_repo=ResearchRepository(session_factory),
        polymarket_service=polymarket_service,
        wallet_intel_service=wallet_service,
        event_signals_service=event_service,
    )
    replay_service = ReplayService(settings=settings, replay_repo=ReplayRepository(session_factory))
    openclaw_bridge = OpenClawBridge(
        settings=settings.model_copy(update={"enable_openclaw_bridge": True}),
        repo=SystemRecordsRepository(session_factory),
        events_repo=events_repo,
    )

    app = FastAPI()
    app.include_router(research_router, prefix="/api/v1")
    app.include_router(replay_router, prefix="/api/v1")
    app.include_router(system_records_router, prefix="/api/v1")
    app.state.research_service = research_service
    app.state.replay_service = replay_service
    app.state.openclaw_bridge = openclaw_bridge

    with TestClient(app) as client:
        backfill_response = client.post(
            "/api/v1/research/backfill-jobs",
            json={"dataset_type": "wallet_observations", "provider_name": "wallet_intel"},
        )
        replay_response = client.post(
            "/api/v1/replay/run",
            json={
                "symbols": ["BTCUSDT"],
                "candles": {
                    "BTCUSDT": {
                        "5m": [
                            {
                                "open_time": "2026-04-08T09:00:00Z",
                                "open": 68000,
                                "high": 68120,
                                "low": 67980,
                                "close": 68100,
                                "volume": 120,
                                "is_closed": True,
                            }
                        ]
                    }
                },
                "fidelity_mode": "low_fidelity",
                "polymarket_snapshots": [{"market_id": "pm_btc", "yes_price": 0.65, "no_price": 0.4}],
            },
        )
        incident_response = client.post(
            "/api/v1/system/incidents",
            json={
                "category": "external_dependency_failure",
                "severity": "medium",
                "source": "tests",
                "impacted_scope": "system",
                "title": "Synthetic incident",
            },
        )
        incident_id = incident_response.json()["incident_id"]
        ack_response = client.post(f"/api/v1/system/incidents/{incident_id}/acknowledge", json={"note": "Seen"})
        resolve_response = client.post(f"/api/v1/system/incidents/{incident_id}/resolve", json={"note": "Cleared"})
        get_response = client.get(f"/api/v1/system/incidents/{incident_id}")

    assert backfill_response.status_code == 200
    assert replay_response.status_code == 200
    assert replay_response.json()["fidelity_metadata"]["precision_claim"] == "coarse_snapshot_replay"
    assert incident_response.status_code == 200
    assert ack_response.json()["status"] == "acknowledged"
    assert resolve_response.json()["status"] == "resolved"
    assert get_response.status_code == 200

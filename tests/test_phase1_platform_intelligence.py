from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.alpha_fusion.service import AlphaFusionService
from app.api.routes.alpha import router as alpha_router
from app.api.routes.features import router as features_router
from app.api.routes.regime import router as regime_router
from app.api.routes.research import router as research_router
from app.api.routes.system_intelligence import router as system_router
from app.config.settings import get_settings
from app.features.service import FeatureService
from app.market_data.types import Candle, TickerSnapshot
from app.persistence.db import get_persistence_engine, get_persistence_session_factory
from app.persistence.models import PersistenceBase
from app.persistence.repositories.alpha_fusion_repo import AlphaFusionRepository
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.feature_runs_repo import FeatureRunsRepository
from app.persistence.repositories.fused_opportunities_repo import FusedOpportunitiesRepository
from app.persistence.repositories.regime_repo import RegimeRepository
from app.persistence.repositories.research_repo import ResearchRepository
from app.regime.service import RegimeService
from app.research.service import ResearchService


def _make_candles(
    *,
    count: int,
    start_price: float,
    step: float,
    start_time: datetime,
    minutes: int,
    tail_steps: list[float] | None = None,
    volume_multiplier: float = 1.0,
) -> list[Candle]:
    candles: list[Candle] = []
    price = start_price
    tail_steps = tail_steps or []
    tail_start = count - len(tail_steps)

    for index in range(count):
        increment = tail_steps[index - tail_start] if index >= tail_start else step
        current_open = price
        current_close = current_open + increment
        high = max(current_open, current_close) + (25.0 + (index % 3))
        low = min(current_open, current_close) - (20.0 + (index % 2))
        volume = (150.0 + index * 4.0) * volume_multiplier
        if index >= count - 4:
            volume *= 1.8

        candles.append(
            Candle(
                open_time=start_time + timedelta(minutes=minutes * index),
                open=current_open,
                high=high,
                low=low,
                close=current_close,
                volume=volume,
                is_closed=True,
            )
        )
        price = current_close

    return candles


class FakeMarketDataService:
    def __init__(self) -> None:
        base_time = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)
        self._candles = {
            ("BTCUSDT", "1h"): _make_candles(
                count=90,
                start_price=67000.0,
                step=45.0,
                start_time=base_time,
                minutes=60,
                tail_steps=[20.0, 30.0, 42.0, 58.0, 70.0, 78.0, 82.0, 95.0],
            ),
            ("BTCUSDT", "15m"): _make_candles(
                count=90,
                start_price=69000.0,
                step=8.0,
                start_time=base_time,
                minutes=15,
                tail_steps=[-4.0, 5.0, 8.0, 12.0, 16.0, 18.0, 22.0, 28.0],
                volume_multiplier=1.2,
            ),
            ("BTCUSDT", "5m"): _make_candles(
                count=90,
                start_price=69200.0,
                step=3.0,
                start_time=base_time,
                minutes=5,
                tail_steps=[-10.0, 2.0, 4.0, 7.0, 9.0, 11.0, 15.0, 20.0, 26.0, 32.0],
                volume_multiplier=1.35,
            ),
        }

    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        return self._candles[(symbol.upper(), timeframe.lower())]

    async def get_snapshot(self, symbol: str) -> TickerSnapshot:
        candles = self._candles[(symbol.upper(), "5m")]
        latest = candles[-1].close
        return TickerSnapshot(
            symbol=symbol.upper(),
            last_price=latest,
            bid_price=latest - 4.0,
            ask_price=latest + 4.0,
        )


def _make_stateful_app(tmp_path: Path) -> FastAPI:
    settings = get_settings().model_copy(
        update={
            "signals_supported_symbols": ["BTCUSDT"],
            "alpha_feature_timeframes": ["5m", "15m", "1h"],
            "persistence_db_url": f"sqlite:///{tmp_path / 'phase1_intel.db'}",
        }
    )
    engine = get_persistence_engine(settings.persistence_db_url)
    PersistenceBase.metadata.create_all(bind=engine)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    events_repo = EventsRepository(session_factory)
    feature_repo = FeatureRunsRepository(session_factory)
    regime_repo = RegimeRepository(session_factory)
    source_repo = AlphaSourcesRepository(session_factory)
    fused_repo = FusedOpportunitiesRepository(session_factory)
    legacy_alpha_repo = AlphaFusionRepository(session_factory)
    research_repo = ResearchRepository(session_factory)
    market_data_service = FakeMarketDataService()
    feature_service = FeatureService(
        settings=settings,
        market_data_service=market_data_service,
        feature_runs_repo=feature_repo,
        events_repo=events_repo,
    )
    regime_service = RegimeService(
        settings=settings,
        feature_service=feature_service,
        regime_repo=regime_repo,
        events_repo=events_repo,
    )
    alpha_service = AlphaFusionService(
        settings=settings,
        market_data_service=market_data_service,
        feature_service=feature_service,
        regime_service=regime_service,
        feature_runs_repo=feature_repo,
        source_repo=source_repo,
        fused_repo=fused_repo,
        fusion_repo=legacy_alpha_repo,
        regime_repo=regime_repo,
        events_repo=events_repo,
    )
    research_service = ResearchService(settings=settings, research_repo=research_repo)
    research_service.bootstrap_defaults()

    app = FastAPI()
    app.include_router(features_router, prefix="/api/v1")
    app.include_router(alpha_router, prefix="/api/v1")
    app.include_router(regime_router, prefix="/api/v1")
    app.include_router(research_router, prefix="/api/v1")
    app.include_router(system_router, prefix="/api/v1")
    app.state.feature_service = feature_service
    app.state.alpha_fusion_service = alpha_service
    app.state.regime_service = regime_service
    app.state.research_service = research_service
    return app


def test_feature_service_exposes_tradingview_like_catalog_and_snapshot(tmp_path: Path) -> None:
    app = _make_stateful_app(tmp_path)
    service = app.state.feature_service

    catalog = service.get_catalog()
    assert len(catalog) >= 10
    assert any(item.name == "squeeze_on" for item in catalog)

    run = __import__("asyncio").run(service.compute_symbol("BTCUSDT", persist=True))
    assert run is not None
    assert run.feature_snapshot is not None
    vector = run.feature_snapshot.timeframes["5m"]
    assert vector.bollinger_width_pct is not None
    assert vector.keltner_width_pct is not None
    assert vector.market_structure in {
        "higher_highs_higher_lows",
        "compressing",
        "balanced",
        "expanding",
        "lower_highs_lower_lows",
    }


def test_regime_service_classifies_and_persists_history(tmp_path: Path) -> None:
    app = _make_stateful_app(tmp_path)
    feature_service = app.state.feature_service
    regime_service = app.state.regime_service
    feature_run = __import__("asyncio").run(feature_service.compute_symbol("BTCUSDT", persist=True))

    snapshot = __import__("asyncio").run(
        regime_service.evaluate_symbol("BTCUSDT", feature_snapshot=feature_run.feature_snapshot)
    )

    assert snapshot is not None
    assert snapshot.regime in {
        "trending_up",
        "trending_down",
        "mean_reverting",
        "volatile_chop",
        "compressed_breakout_setup",
        "risk_off",
    }
    assert regime_service.list_history(symbol="BTCUSDT", limit=5)


def test_phase1_endpoints_return_features_sources_regimes_and_summary(tmp_path: Path) -> None:
    app = _make_stateful_app(tmp_path)

    with TestClient(app) as client:
        catalog_response = client.get("/api/v1/features/catalog")
        compute_response = client.post("/api/v1/features/compute", json={"symbol": "BTCUSDT"})
        fused_response = client.post("/api/v1/alpha/fused", json={"symbols": ["BTCUSDT"]})
        sources_response = client.get("/api/v1/alpha/sources", params={"symbol": "BTCUSDT"})
        current_regime_response = client.get("/api/v1/regime/current", params={"symbol": "BTCUSDT"})
        history_response = client.get("/api/v1/regime/history", params={"symbol": "BTCUSDT"})
        research_response = client.get("/api/v1/research/experiments")
        summary_response = client.get("/api/v1/system/intelligence/summary")

    assert catalog_response.status_code == 200
    assert catalog_response.json()["count"] >= 10

    assert compute_response.status_code == 200
    compute_payload = compute_response.json()
    assert compute_payload["feature_snapshot"]["timeframes"]["5m"]["bollinger_width_pct"] is not None

    assert fused_response.status_code == 200
    fused_payload = fused_response.json()
    assert fused_payload["count"] == 1
    item = fused_payload["items"][0]
    assert item["confidence_band"] in {"low", "medium", "high"}
    assert item["regime"] is not None

    assert sources_response.status_code == 200
    assert sources_response.json()["count"] >= 2

    assert current_regime_response.status_code == 200
    assert current_regime_response.json()["count"] == 1

    assert history_response.status_code == 200
    assert history_response.json()["count"] >= 1

    assert research_response.status_code == 200
    assert research_response.json()["count"] >= 1

    assert summary_response.status_code == 200
    assert summary_response.json()["safe_mode"]["enable_live_trading"] is False

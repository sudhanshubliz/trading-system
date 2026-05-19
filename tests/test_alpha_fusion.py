from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.alpha_fusion.feature_engine import TradingViewFeatureEngine
from app.alpha_fusion.service import AlphaFusionService
from app.api.routes.alpha import router as alpha_router
from app.config.settings import get_settings
from app.market_data.types import Candle, TickerSnapshot


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


def test_tradingview_feature_engine_builds_multitimeframe_snapshot() -> None:
    settings = get_settings().model_copy(update={"alpha_feature_timeframes": ["5m", "15m", "1h"]})
    engine = TradingViewFeatureEngine(settings=settings)
    service = FakeMarketDataService()
    base_time = datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc)
    snapshot = engine.build_snapshot(
        symbol="BTCUSDT",
        candles_by_timeframe={
            "1h": service._candles[("BTCUSDT", "1h")],
            "15m": service._candles[("BTCUSDT", "15m")],
            "5m": service._candles[("BTCUSDT", "5m")],
        },
        generated_at=base_time,
        market_price=service._candles[("BTCUSDT", "5m")][-1].close,
    )

    assert snapshot is not None
    assert snapshot.symbol == "BTCUSDT"
    assert set(snapshot.timeframes) == {"5m", "15m", "1h"}
    assert snapshot.feature_coverage == 1.0
    assert "1h" in snapshot.bullish_timeframes
    assert snapshot.timeframes["5m"].atr_pct is not None
    assert snapshot.timeframes["5m"].breakout_bias > 0


def test_alpha_fusion_service_produces_explainable_long_signal() -> None:
    settings = get_settings().model_copy(
        update={
            "signals_supported_symbols": ["BTCUSDT"],
            "alpha_feature_timeframes": ["5m", "15m", "1h"],
        }
    )
    service = AlphaFusionService(settings=settings, market_data_service=FakeMarketDataService())
    items = __import__("asyncio").run(service.evaluate_symbols(["BTCUSDT"]))

    assert len(items) == 1
    signal = items[0]
    assert signal.symbol == "BTCUSDT"
    assert signal.direction == "long"
    assert signal.score >= settings.alpha_long_threshold
    assert signal.confidence > 0.55
    assert any("trend" in line.lower() for line in signal.explanation)


def test_alpha_endpoints_return_features_and_fused_signals() -> None:
    settings = get_settings().model_copy(
        update={
            "signals_supported_symbols": ["BTCUSDT"],
            "alpha_feature_timeframes": ["5m", "15m", "1h"],
        }
    )
    app = FastAPI()
    app.include_router(alpha_router, prefix="/api/v1")
    app.state.alpha_fusion_service = AlphaFusionService(
        settings=settings,
        market_data_service=FakeMarketDataService(),
    )

    with TestClient(app) as client:
        features_response = client.get("/api/v1/alpha/features/BTCUSDT")
        fused_response = client.post("/api/v1/alpha/fused", json={"symbols": ["BTCUSDT"]})

    assert features_response.status_code == 200
    features_payload = features_response.json()
    assert features_payload["symbol"] == "BTCUSDT"
    assert set(features_payload["timeframes"]) == {"5m", "15m", "1h"}

    assert fused_response.status_code == 200
    fused_payload = fused_response.json()
    assert fused_payload["count"] == 1
    first_item = fused_payload["items"][0]
    assert first_item["direction"] == "long"
    assert "components" in first_item
    assert "feature_snapshot" in first_item

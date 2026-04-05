from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.market_data.types import Candle
from app.signals.service import SignalService


def _make_candles(
    *,
    count: int,
    start_price: float,
    step: float,
    start_time: datetime,
    minutes: int,
    breakout_boost: float = 0.0,
    tail_steps: list[float] | None = None,
) -> list[Candle]:
    candles: list[Candle] = []
    price = start_price
    tail_steps = tail_steps or []
    tail_start = count - len(tail_steps)
    for index in range(count):
        current_step = tail_steps[index - tail_start] if index >= tail_start else step
        current_open = price
        current_close = current_open + current_step
        if index == count - 1:
            current_close += breakout_boost
        high = max(current_open, current_close) + 95.0
        low = min(current_open, current_close) - 70.0
        volume = 150.0 + index
        if index == count - 1:
            volume *= 2.5

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
        base_time = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
        self._candles = {
            ("BTCUSDT", "1h"): _make_candles(
                count=80,
                start_price=67000.0,
                step=18.0,
                start_time=base_time,
                minutes=60,
            ),
            ("BTCUSDT", "15m"): _make_candles(
                count=80,
                start_price=68100.0,
                step=2.0,
                start_time=base_time,
                minutes=15,
            ),
            ("BTCUSDT", "5m"): _make_candles(
                count=80,
                start_price=68200.0,
                step=1.5,
                start_time=base_time,
                minutes=5,
                tail_steps=[-20.0, -18.0, -15.0, -12.0, -10.0, 2.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0],
            ),
            ("ETHUSDT", "1h"): _make_candles(
                count=20,
                start_price=3200.0,
                step=1.0,
                start_time=base_time,
                minutes=60,
            ),
            ("ETHUSDT", "15m"): _make_candles(
                count=20,
                start_price=3300.0,
                step=0.3,
                start_time=base_time,
                minutes=15,
            ),
            ("ETHUSDT", "5m"): _make_candles(
                count=20,
                start_price=3310.0,
                step=0.2,
                start_time=base_time,
                minutes=5,
            ),
        }

    async def get_health(self) -> dict[str, object]:
        return {"status": "ok"}

    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        return self._candles.get((symbol.upper(), timeframe.lower()), [])


def test_signal_evaluation_endpoint_returns_candidate_signals() -> None:
    from app.main import app

    fake_market_data_service = FakeMarketDataService()

    with TestClient(app) as client:
        app.state.market_data_service = fake_market_data_service
        app.state.signal_service = SignalService(
            market_data_service=fake_market_data_service,
        )
        response = client.post("/api/v1/signals/evaluate", json={"symbols": ["BTCUSDT", "ETHUSDT"]})

    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert payload["count"] >= 1

    first_item = payload["items"][0]
    for key in [
        "signal_id",
        "symbol",
        "strategy_name",
        "confidence_score",
        "entry_price",
        "stop_loss",
        "target_1",
        "target_2",
        "reward_risk_ratio",
        "rationale",
        "indicators_snapshot",
        "generated_at",
        "status",
    ]:
        assert key in first_item


def test_signal_evaluation_returns_empty_for_insufficient_candles() -> None:
    from app.main import app

    class EmptyMarketDataService:
        async def get_health(self) -> dict[str, object]:
            return {"status": "ok"}

        async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
            return []

    with TestClient(app) as client:
        market_data_service = EmptyMarketDataService()
        app.state.market_data_service = market_data_service
        app.state.signal_service = SignalService(market_data_service=market_data_service)
        response = client.post("/api/v1/signals/evaluate", json={"symbols": ["BTCUSDT"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 0
    assert payload["items"] == []

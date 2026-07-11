from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.market_data.types import Candle
from app.signals.types import IndicatorSnapshot, TimeframeIndicatorSnapshot
from app.signals.service import SignalService
from app.strategies.base import StrategyContext
from app.strategies.trend_follow import TrendFollowContinuationStrategy


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


def test_signal_evaluation_can_emit_short_candidate_signals() -> None:
    from app.main import app
    from app.config.settings import get_settings

    class BearishMarketDataService:
        def __init__(self) -> None:
            base_time = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
            self._candles = {
                ("BTCUSDT", "1h"): _make_candles(
                    count=80,
                    start_price=70000.0,
                    step=-22.0,
                    start_time=base_time,
                    minutes=60,
                ),
                ("BTCUSDT", "15m"): _make_candles(
                    count=80,
                    start_price=68400.0,
                    step=-1.0,
                    start_time=base_time,
                    minutes=15,
                ),
                ("BTCUSDT", "5m"): _make_candles(
                    count=80,
                    start_price=68200.0,
                    step=-1.0,
                    start_time=base_time,
                    minutes=5,
                    tail_steps=[20.0, 18.0, 16.0, 14.0, 12.0, -3.0, -4.0, -6.0, -7.0, -8.0, -10.0, -11.0, -12.0, -14.0],
                ),
            }

        async def get_health(self) -> dict[str, object]:
            return {"status": "ok"}

        async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
            return self._candles.get((symbol.upper(), timeframe.lower()), [])

    settings = get_settings().model_copy(
        update={
            "signals_supported_symbols": ["BTCUSDT"],
            "signals_min_trigger_range_pct": 0.05,
        }
    )

    with TestClient(app) as client:
        market_data_service = BearishMarketDataService()
        app.state.market_data_service = market_data_service
        app.state.signal_service = SignalService(
            settings=settings,
            market_data_service=market_data_service,
        )
        response = client.post("/api/v1/signals/evaluate", json={"symbols": ["BTCUSDT"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert payload["items"][0]["side"] == "short"


def test_signal_evaluation_short_side_allows_bearish_continuation_above_neutral_rsi() -> None:
    from app.main import app
    from app.config.settings import get_settings

    class ModerateBearishMarketDataService:
        def __init__(self) -> None:
            base_time = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
            self._candles = {
                ("BTCUSDT", "1h"): _make_candles(
                    count=80,
                    start_price=70000.0,
                    step=-20.0,
                    start_time=base_time,
                    minutes=60,
                ),
                ("BTCUSDT", "15m"): _make_candles(
                    count=80,
                    start_price=68600.0,
                    step=2.0,
                    start_time=base_time,
                    minutes=15,
                    tail_steps=[7.0, 6.0, 5.0, 3.0, 2.0, -1.0, -2.0, -3.0, -4.0, -5.0],
                ),
                ("BTCUSDT", "5m"): _make_candles(
                    count=80,
                    start_price=68200.0,
                    step=1.0,
                    start_time=base_time,
                    minutes=5,
                    tail_steps=[24.0, 22.0, 20.0, 18.0, 16.0, -4.0, -5.0, -6.0, -8.0, -10.0, -12.0, -13.0],
                ),
            }

        async def get_health(self) -> dict[str, object]:
            return {"status": "ok"}

        async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
            return self._candles.get((symbol.upper(), timeframe.lower()), [])

    settings = get_settings().model_copy(
        update={
            "signals_supported_symbols": ["BTCUSDT"],
            "signals_min_trigger_range_pct": 0.05,
            "signals_rsi_short_max": 60.0,
        }
    )

    with TestClient(app) as client:
        market_data_service = ModerateBearishMarketDataService()
        app.state.market_data_service = market_data_service
        app.state.signal_service = SignalService(
            settings=settings,
            market_data_service=market_data_service,
        )
        response = client.post("/api/v1/signals/evaluate", json={"symbols": ["BTCUSDT"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert any(item["side"] == "short" for item in payload["items"])


def test_trend_follow_allows_marginal_pullback_and_range_when_structure_is_clean() -> None:
    from app.config.settings import get_settings

    settings = get_settings().model_copy(
        update={
            "signals_pullback_tolerance_pct": 0.007,
            "signals_min_trigger_range_pct": 0.06,
        }
    )
    base_time = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
    regime_candles = _make_candles(
        count=80,
        start_price=70000.0,
        step=20.0,
        start_time=base_time,
        minutes=60,
    )
    setup_candles = _make_candles(
        count=80,
        start_price=71300.0,
        step=2.0,
        start_time=base_time,
        minutes=15,
    )
    trigger_candles = _make_candles(
        count=80,
        start_price=71400.0,
        step=1.0,
        start_time=base_time,
        minutes=5,
        tail_steps=[-18.0, -14.0, -10.0, -6.0, -2.0, 3.0, 5.0, 7.0, 9.0, 11.0],
    )
    latest_close = trigger_candles[-1].close
    indicators = IndicatorSnapshot(
        timeframes={
            settings.signals_regime_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=71450.0,
                ema_slow=71350.0,
                rsi=58.0,
                vwap=71320.0,
                macd=18.0,
                macd_signal=12.0,
                macd_hist=6.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.07,
            ),
            settings.signals_setup_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 90.0,
                ema_slow=latest_close - 120.0,
                rsi=55.0,
                vwap=latest_close / (1.0 + 0.0065),
                macd=8.0,
                macd_signal=5.0,
                macd_hist=3.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.07,
            ),
            settings.signals_trigger_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 10.0,
                ema_slow=latest_close - 15.0,
                rsi=58.0,
                vwap=latest_close - 80.0,
                macd=4.0,
                macd_signal=2.0,
                macd_hist=2.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.07,
            ),
        }
    )
    context = StrategyContext(
        symbol="BTCUSDT",
        regime_candles=regime_candles,
        setup_candles=setup_candles,
        trigger_candles=trigger_candles,
        indicators=indicators,
        settings=settings,
        generated_at=base_time + timedelta(hours=10),
        signal_id_factory=lambda symbol, strategy, side, generated_at: f"{symbol}-{strategy}-{side}",
    )

    signal = TrendFollowContinuationStrategy().evaluate(context)

    assert signal is not None
    assert signal.side == "long"


def test_trend_follow_allows_shallow_counter_color_trigger_when_continuation_is_strong() -> None:
    from app.config.settings import get_settings

    settings = get_settings().model_copy(
        update={
            "signals_pullback_tolerance_pct": 0.007,
            "signals_min_trigger_range_pct": 0.06,
            "signals_countertrend_trigger_body_to_range_ratio": 0.4,
            "signals_countertrend_trigger_rsi_buffer": 5.0,
            "signals_countertrend_trigger_min_regime_gap_pct": 0.0001,
        }
    )
    base_time = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
    regime_candles = _make_candles(
        count=80,
        start_price=70000.0,
        step=18.0,
        start_time=base_time,
        minutes=60,
    )
    setup_candles = _make_candles(
        count=80,
        start_price=71300.0,
        step=2.0,
        start_time=base_time,
        minutes=15,
    )
    trigger_candles = _make_candles(
        count=80,
        start_price=71400.0,
        step=1.0,
        start_time=base_time,
        minutes=5,
        tail_steps=[-12.0, -8.0, -4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0],
    )
    latest = trigger_candles[-1]
    counter_color_close = latest.open - 8.0
    trigger_candles[-1] = Candle(
        open_time=latest.open_time,
        open=latest.open,
        high=latest.high,
        low=min(latest.low, counter_color_close - 2.0),
        close=counter_color_close,
        volume=latest.volume,
        is_closed=True,
    )
    latest_close = trigger_candles[-1].close
    indicators = IndicatorSnapshot(
        timeframes={
            settings.signals_regime_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=71480.0,
                ema_slow=71360.0,
                rsi=59.0,
                vwap=71340.0,
                macd=18.0,
                macd_signal=11.0,
                macd_hist=7.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.08,
            ),
            settings.signals_setup_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 80.0,
                ema_slow=latest_close - 120.0,
                rsi=56.0,
                vwap=latest_close / (1.0 + 0.0064),
                macd=7.0,
                macd_signal=4.0,
                macd_hist=3.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.08,
            ),
            settings.signals_trigger_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 12.0,
                ema_slow=latest_close - 18.0,
                rsi=58.0,
                vwap=latest_close - 90.0,
                macd=4.0,
                macd_signal=2.5,
                macd_hist=1.5,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.08,
            ),
        }
    )
    context = StrategyContext(
        symbol="BTCUSDT",
        regime_candles=regime_candles,
        setup_candles=setup_candles,
        trigger_candles=trigger_candles,
        indicators=indicators,
        settings=settings,
        generated_at=base_time + timedelta(hours=10),
        signal_id_factory=lambda symbol, strategy, side, generated_at: f"{symbol}-{strategy}-{side}",
    )

    signal = TrendFollowContinuationStrategy().evaluate(context)

    assert signal is not None
    assert signal.side == "long"
    assert any("counter-color" in line for line in signal.rationale)


def test_trend_follow_allows_strong_regime_pullback_when_vwap_lags_fast_ema() -> None:
    from app.config.settings import get_settings

    settings = get_settings().model_copy(
        update={
            "signals_pullback_tolerance_pct": 0.007,
            "signals_trend_pullback_vwap_slack_pct": 0.005,
            "signals_trend_pullback_strong_regime_gap_pct": 0.002,
        }
    )
    base_time = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
    regime_candles = _make_candles(
        count=80,
        start_price=70000.0,
        step=24.0,
        start_time=base_time,
        minutes=60,
    )
    setup_candles = _make_candles(
        count=80,
        start_price=76800.0,
        step=3.0,
        start_time=base_time,
        minutes=15,
    )
    trigger_candles = _make_candles(
        count=80,
        start_price=77000.0,
        step=2.0,
        start_time=base_time,
        minutes=5,
        tail_steps=[-12.0, -8.0, -4.0, 4.0, 6.0, 8.0, 9.0, 10.0, 11.0, 12.0],
    )
    latest_close = trigger_candles[-1].close
    indicators = IndicatorSnapshot(
        timeframes={
            settings.signals_regime_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 120.0,
                ema_slow=latest_close - 305.0,
                rsi=60.0,
                vwap=latest_close - 220.0,
                macd=19.0,
                macd_signal=11.0,
                macd_hist=8.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.08,
            ),
            settings.signals_setup_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 90.0,
                ema_slow=latest_close - 150.0,
                rsi=57.0,
                vwap=latest_close / (1.0 + 0.0115),
                macd=8.0,
                macd_signal=5.0,
                macd_hist=3.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.08,
            ),
            settings.signals_trigger_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 10.0,
                ema_slow=latest_close - 16.0,
                rsi=58.0,
                vwap=latest_close - 70.0,
                macd=4.0,
                macd_signal=2.0,
                macd_hist=2.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.08,
            ),
        }
    )
    context = StrategyContext(
        symbol="BTCUSDT",
        regime_candles=regime_candles,
        setup_candles=setup_candles,
        trigger_candles=trigger_candles,
        indicators=indicators,
        settings=settings,
        generated_at=base_time + timedelta(hours=10),
        signal_id_factory=lambda symbol, strategy, side, generated_at: f"{symbol}-{strategy}-{side}",
    )

    signal = TrendFollowContinuationStrategy().evaluate(context)

    assert signal is not None
    assert signal.side == "long"
    assert any("VWAP is lagging" in line for line in signal.rationale)


def test_trend_follow_still_rejects_vwap_lag_when_regime_is_not_strong_enough() -> None:
    from app.config.settings import get_settings

    settings = get_settings().model_copy(
        update={
            "signals_pullback_tolerance_pct": 0.007,
            "signals_trend_pullback_vwap_slack_pct": 0.005,
            "signals_trend_pullback_strong_regime_gap_pct": 0.002,
        }
    )
    base_time = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
    regime_candles = _make_candles(
        count=80,
        start_price=70000.0,
        step=10.0,
        start_time=base_time,
        minutes=60,
    )
    setup_candles = _make_candles(
        count=80,
        start_price=76800.0,
        step=3.0,
        start_time=base_time,
        minutes=15,
    )
    trigger_candles = _make_candles(
        count=80,
        start_price=77000.0,
        step=2.0,
        start_time=base_time,
        minutes=5,
        tail_steps=[-12.0, -8.0, -4.0, 4.0, 6.0, 8.0, 9.0, 10.0, 11.0, 12.0],
    )
    latest_close = trigger_candles[-1].close
    indicators = IndicatorSnapshot(
        timeframes={
            settings.signals_regime_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 85.0,
                ema_slow=latest_close - 145.0,
                rsi=56.0,
                vwap=latest_close - 180.0,
                macd=12.0,
                macd_signal=8.0,
                macd_hist=4.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.08,
            ),
            settings.signals_setup_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 95.0,
                ema_slow=latest_close - 145.0,
                rsi=56.0,
                vwap=latest_close / (1.0 + 0.0115),
                macd=8.0,
                macd_signal=5.0,
                macd_hist=3.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.08,
            ),
            settings.signals_trigger_timeframe: TimeframeIndicatorSnapshot(
                ema_fast=latest_close - 10.0,
                ema_slow=latest_close - 16.0,
                rsi=58.0,
                vwap=latest_close - 70.0,
                macd=4.0,
                macd_signal=2.0,
                macd_hist=2.0,
                latest_close=latest_close,
                previous_close=trigger_candles[-2].close,
                latest_volume=trigger_candles[-1].volume,
                average_volume=180.0,
                average_range_pct=0.08,
            ),
        }
    )
    context = StrategyContext(
        symbol="BTCUSDT",
        regime_candles=regime_candles,
        setup_candles=setup_candles,
        trigger_candles=trigger_candles,
        indicators=indicators,
        settings=settings,
        generated_at=base_time + timedelta(hours=10),
        signal_id_factory=lambda symbol, strategy, side, generated_at: f"{symbol}-{strategy}-{side}",
    )

    signal = TrendFollowContinuationStrategy().evaluate(context)

    assert signal is None

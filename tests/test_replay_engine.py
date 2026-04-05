from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.replay.metrics import calculate_drawdown, calculate_expectancy
from app.replay.types import EquityPoint, ReplayTradeResult


def _make_candles(
    *,
    count: int,
    start_price: float,
    step: float,
    start_time: datetime,
    minutes: int,
    tail_steps: list[float] | None = None,
) -> list[dict[str, object]]:
    candles: list[dict[str, object]] = []
    price = start_price
    tail_steps = tail_steps or []
    tail_start = count - len(tail_steps)
    for index in range(count):
        current_step = tail_steps[index - tail_start] if index >= tail_start else step
        current_open = price
        current_close = current_open + current_step
        high = max(current_open, current_close) + 95.0
        low = min(current_open, current_close) - 600.0
        volume = 150.0 + index
        if index == count - 1:
            volume *= 2.5

        candles.append(
            {
                "open_time": (start_time + timedelta(minutes=minutes * index)).isoformat(),
                "open": current_open,
                "high": high,
                "low": low,
                "close": current_close,
                "volume": volume,
                "is_closed": True,
            }
        )
        price = current_close

    return candles


def _replay_payload() -> dict[str, object]:
    end_time = datetime(2026, 4, 2, 18, 35, tzinfo=timezone.utc)
    base_time_1h = end_time - timedelta(hours=79)
    base_time_15m = end_time - timedelta(minutes=15 * 79)
    base_time_5m = end_time - timedelta(minutes=5 * 79)
    return {
        "symbols": ["BTCUSDT"],
        "initial_balance": 500000.0,
        "candles": {
            "BTCUSDT": {
                "1h": _make_candles(
                    count=80,
                    start_price=67000.0,
                    step=18.0,
                    start_time=base_time_1h,
                    minutes=60,
                ),
                "15m": _make_candles(
                    count=80,
                    start_price=68100.0,
                    step=2.0,
                    start_time=base_time_15m,
                    minutes=15,
                ),
                "5m": _make_candles(
                    count=80,
                    start_price=68200.0,
                    step=1.5,
                    start_time=base_time_5m,
                    minutes=5,
                    tail_steps=[-20.0, -18.0, -15.0, -12.0, -10.0, 2.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0],
                ),
            }
        },
    }


def test_replay_bullish_candles_produce_trade() -> None:
    from app.main import app

    with TestClient(app) as client:
        response = client.post("/api/v1/replay/run", json=_replay_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total_trades"] >= 1


def test_replay_empty_dataset_zero_safe() -> None:
    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/replay/run",
            json={"symbols": ["BTCUSDT"], "initial_balance": 10000.0, "candles": {}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total_trades"] == 0
    assert payload["metrics"]["ending_balance"] == 10000.0


def test_drawdown_metric_is_correct() -> None:
    equity_curve = [
        EquityPoint(timestamp=datetime(2026, 4, 1, tzinfo=timezone.utc), equity=10000.0, realized_pnl=0.0, unrealized_pnl=0.0),
        EquityPoint(timestamp=datetime(2026, 4, 2, tzinfo=timezone.utc), equity=10200.0, realized_pnl=200.0, unrealized_pnl=0.0),
        EquityPoint(timestamp=datetime(2026, 4, 3, tzinfo=timezone.utc), equity=9900.0, realized_pnl=-100.0, unrealized_pnl=0.0),
    ]
    drawdown_abs, drawdown_pct = calculate_drawdown(equity_curve)
    assert drawdown_abs == 300.0
    assert round(drawdown_pct, 4) == round((300.0 / 10200.0) * 100, 4)


def test_expectancy_metric_is_correct() -> None:
    trades = [
        ReplayTradeResult(
            trade_id="t1",
            position_id="p1",
            symbol="BTCUSDT",
            side="long",
            strategy_name="trend_follow_continuation",
            entry_price=100.0,
            exit_price=110.0,
            quantity=1.0,
            opened_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            closed_at=datetime(2026, 4, 1, 1, tzinfo=timezone.utc),
            realized_pnl=10.0,
            exit_reason="target_1",
            status="closed",
        ),
        ReplayTradeResult(
            trade_id="t2",
            position_id="p2",
            symbol="BTCUSDT",
            side="long",
            strategy_name="breakout_confirmation",
            entry_price=100.0,
            exit_price=95.0,
            quantity=1.0,
            opened_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
            closed_at=datetime(2026, 4, 2, 1, tzinfo=timezone.utc),
            realized_pnl=-5.0,
            exit_reason="stop_loss",
            status="closed",
        ),
    ]
    assert calculate_expectancy(trades) == 2.5


def test_replay_metrics_endpoint_shape() -> None:
    from app.main import app

    with TestClient(app) as client:
        run_response = client.post("/api/v1/replay/run", json=_replay_payload())
        run_id = run_response.json()["run_id"]
        metrics_response = client.get(f"/api/v1/replay/runs/{run_id}/metrics")

    assert metrics_response.status_code == 200
    payload = metrics_response.json()
    for key in [
        "total_trades",
        "winning_trades",
        "losing_trades",
        "win_rate",
        "profit_factor",
        "expectancy",
        "max_drawdown_abs",
        "max_drawdown_pct",
        "realized_pnl_total",
        "unrealized_pnl_final",
        "ending_balance",
        "equity_curve",
    ]:
        assert key in payload

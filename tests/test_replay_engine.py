from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.market_data.types import Candle
from app.replay.engine import ReplayEngine, ReplayMarketDataService
from app.replay.metrics import build_replay_metrics, calculate_drawdown, calculate_expectancy
from app.replay.types import EquityPoint, ReplayRun, ReplayTradeResult
from app.replay.walk_forward import build_walk_forward_report


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


def test_replay_exposes_completed_candles_only_at_close_boundary() -> None:
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    first = Candle(start, 100.0, 102.0, 99.0, 101.0, 10.0, True)
    second = Candle(start + timedelta(minutes=5), 101.0, 110.0, 100.0, 109.0, 12.0, True)
    source = {"BTCUSDT": {"5m": [first, second]}}
    market_data = ReplayMarketDataService(source, {}, "5m")

    market_data.set_time(start + timedelta(minutes=5))
    visible_at_first_close = asyncio.run(market_data.get_candles("BTCUSDT", "5m"))
    market_data.set_time(start + timedelta(minutes=10))
    visible_at_second_close = asyncio.run(market_data.get_candles("BTCUSDT", "5m"))

    assert visible_at_first_close == [first]
    assert visible_at_second_close == [first, second]
    assert ReplayEngine(get_settings())._build_events(source, ["BTCUSDT"]) == [
        (start + timedelta(minutes=5), {"BTCUSDT"}),
        (start + timedelta(minutes=10), {"BTCUSDT"}),
    ]


def test_replay_bullish_candles_produce_trade() -> None:
    from app.main import app

    with TestClient(app) as client:
        response = client.post("/api/v1/replay/run", json=_replay_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total_trades"] >= 1
    assert payload["metrics"]["fees_paid_total"] > 0
    assert all(item["fees_paid"] > 0 for item in payload["trades"])


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
        "gross_realized_pnl_total",
        "fees_paid_total",
        "slippage_cost_total",
        "turnover_notional",
    ]:
        assert key in payload


def test_walk_forward_report_requires_90_days_and_positive_folds() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=90)
    pnls = [10.0, 10.0, -5.0]
    trades = [
        ReplayTradeResult(
            trade_id=f"wf_trade_{index}",
            position_id=f"wf_position_{index}",
            symbol="BTCUSDT",
            side="long",
            strategy_name="trend_follow_continuation",
            entry_price=100.0,
            exit_price=110.0 if pnl > 0 else 95.0,
            quantity=1.0,
            opened_at=start + timedelta(days=(index * 30) + 10),
            closed_at=start + timedelta(days=(index * 30) + 15),
            realized_pnl=pnl,
            exit_reason="target_2" if pnl > 0 else "stop_loss",
            status="closed",
            gross_realized_pnl=pnl + 1.0,
            fees_paid=1.0,
            slippage_cost=0.4,
        )
        for index, pnl in enumerate(pnls)
    ]
    equity_curve = [
        EquityPoint(timestamp=start, equity=5000.0, realized_pnl=0.0, unrealized_pnl=0.0),
        EquityPoint(timestamp=end, equity=5015.0, realized_pnl=15.0, unrealized_pnl=0.0),
    ]
    run = ReplayRun(
        run_id="rpl_walk_forward",
        status="completed",
        symbols=["BTCUSDT"],
        initial_balance=5000.0,
        total_steps=100,
        started_at=start,
        completed_at=end,
        trades=trades,
        metrics=build_replay_metrics(initial_balance=5000.0, trades=trades, equity_curve=equity_curve),
    )

    report = build_walk_forward_report(
        run,
        start_time=start,
        end_time=end,
        fold_count=3,
        minimum_days=90,
        minimum_trades=3,
        minimum_profit_factor=1.2,
        maximum_drawdown_pct=25.0,
    )
    short_report = build_walk_forward_report(
        run,
        start_time=start,
        end_time=end - timedelta(days=1),
        fold_count=3,
        minimum_days=90,
        minimum_trades=3,
        minimum_profit_factor=1.2,
        maximum_drawdown_pct=25.0,
    )

    assert report.passed is True
    assert report.positive_fold_count == 2
    assert report.fees_paid == 3.0
    assert short_report.passed is False
    assert "minimum_evidence_days_not_met" in short_report.blockers

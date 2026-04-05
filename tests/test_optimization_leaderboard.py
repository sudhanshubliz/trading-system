from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.optimization.service import OptimizationService


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


def _write_replay_files(tmp_path: Path) -> dict[str, dict[str, str]]:
    end_time = datetime(2026, 4, 2, 18, 35, tzinfo=timezone.utc)
    base_time_1h = end_time - timedelta(hours=79)
    base_time_15m = end_time - timedelta(minutes=15 * 79)
    base_time_5m = end_time - timedelta(minutes=5 * 79)

    candles_by_timeframe = {
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

    files: dict[str, dict[str, str]] = {"BTCUSDT": {}}
    for timeframe, candles in candles_by_timeframe.items():
        path = tmp_path / f"btc_{timeframe}.json"
        path.write_text(json.dumps(candles))
        files["BTCUSDT"][timeframe] = str(path)
    return files


def _make_service() -> OptimizationService:
    settings = get_settings().model_copy(
        update={
            "optimization_store_limit": 20,
            "optimization_max_combinations": 50,
            "optimization_default_symbols": ["BTCUSDT"],
            "optimization_default_initial_balance": 500000.0,
            "optimization_min_trades": 0,
            "optimization_min_profit_factor": 0.0,
            "optimization_max_drawdown_pct": 100.0,
            "optimization_require_walk_forward": False,
        }
    )
    return OptimizationService(settings=settings)


def test_leaderboard_endpoint_returns_expected_shape(tmp_path: Path) -> None:
    from app.main import app

    payload = {
        "symbols": ["BTCUSDT"],
        "initial_balance": 500000.0,
        "data_files": _write_replay_files(tmp_path),
        "parameter_grid": {
            "ema_fast_periods": [20],
            "ema_slow_periods": [50],
            "rsi_periods": [14],
            "breakout_lookbacks": [20],
            "min_confidence_scores": [60, 95],
            "min_reward_risk_ratios": [1.5],
        },
    }

    with TestClient(app) as client:
        app.state.optimization_service = _make_service()
        run_response = client.post("/api/v1/optimization/run", json=payload)
        run_id = run_response.json()["run_id"]
        leaderboard_response = client.get(f"/api/v1/optimization/runs/{run_id}/leaderboard")

    assert run_response.status_code == 200
    assert leaderboard_response.status_code == 200
    body = leaderboard_response.json()
    assert body["count"] >= 1
    first_item = body["items"][0]
    for key in [
        "config_id",
        "parameters",
        "total_trades",
        "win_rate",
        "net_pnl",
        "expectancy",
        "profit_factor",
        "max_drawdown_pct",
        "average_hold_minutes",
        "robustness_score",
        "passed_guardrails",
        "guardrail_failures",
        "walk_forward_results",
    ]:
        assert key in first_item

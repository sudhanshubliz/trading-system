from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config.settings import get_settings
from app.optimization.grid import build_parameter_grid
from app.optimization.service import OptimizationService
from app.optimization.types import OptimizationParameterGrid


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
        path = tmp_path / f"btcusdt_{timeframe}.json"
        path.write_text(json.dumps(candles))
        files["BTCUSDT"][timeframe] = str(path)
    return files


def _make_service(**overrides) -> OptimizationService:
    settings = get_settings().model_copy(
        update={
            "optimization_store_limit": 20,
            "optimization_max_combinations": 50,
            "optimization_default_symbols": ["BTCUSDT"],
            "optimization_default_initial_balance": 500000.0,
            "optimization_min_trades": 0,
            "optimization_min_profit_factor": 0.0,
            "optimization_max_drawdown_pct": 100.0,
            "optimization_walk_forward_splits": 3,
            "optimization_require_walk_forward": False,
            **overrides,
        }
    )
    return OptimizationService(settings=settings)


def test_build_parameter_grid_filters_invalid_combinations() -> None:
    grid = OptimizationParameterGrid(
        ema_fast_periods=[20, 60],
        ema_slow_periods=[10, 50],
        rsi_periods=[14, 1],
        breakout_lookbacks=[20, 1],
        min_confidence_scores=[60, 150],
        min_reward_risk_ratios=[1.5, 0.0],
    )

    combinations = build_parameter_grid(grid, max_combinations=100)

    assert len(combinations) == 1
    assert combinations[0].ema_fast_period == 20
    assert combinations[0].ema_slow_period == 50
    assert combinations[0].rsi_period == 14
    assert combinations[0].breakout_lookback == 20
    assert combinations[0].min_confidence_score == 60
    assert combinations[0].min_reward_risk_ratio == 1.5


async def _run_service(service: OptimizationService, payload: dict[str, object]):
    return await service.run_optimization(payload)


def test_optimization_run_returns_ranked_results(tmp_path: Path) -> None:
    service = _make_service()
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
        "walk_forward_splits": 2,
    }

    import asyncio

    result = asyncio.run(_run_service(service, payload))

    assert result.status == "completed"
    assert result.evaluated_combinations == 2
    assert len(result.leaderboard) == 2
    assert result.leaderboard[0].robustness_score >= result.leaderboard[1].robustness_score
    assert result.leaderboard[0].net_pnl >= result.leaderboard[1].net_pnl
    assert all(math.isfinite(row.robustness_score) for row in result.leaderboard)


def test_guardrails_mark_weak_configs_as_failed(tmp_path: Path) -> None:
    service = _make_service(
        optimization_min_trades=5,
        optimization_min_profit_factor=2.0,
        optimization_max_drawdown_pct=1.0,
        optimization_require_walk_forward=True,
    )
    payload = {
        "symbols": ["BTCUSDT"],
        "initial_balance": 500000.0,
        "data_files": _write_replay_files(tmp_path),
        "parameter_grid": {
            "ema_fast_periods": [20],
            "ema_slow_periods": [50],
            "rsi_periods": [14],
            "breakout_lookbacks": [20],
            "min_confidence_scores": [95],
            "min_reward_risk_ratios": [3.0],
        },
        "walk_forward_splits": 3,
    }

    import asyncio

    result = asyncio.run(_run_service(service, payload))

    assert result.status == "completed"
    assert len(result.leaderboard) == 1
    row = result.leaderboard[0]
    assert row.passed_guardrails is False
    assert row.guardrail_failures


def test_walk_forward_validation_produces_fold_results(tmp_path: Path) -> None:
    service = _make_service(
        optimization_require_walk_forward=True,
        optimization_walk_forward_splits=3,
    )
    payload = {
        "symbols": ["BTCUSDT"],
        "initial_balance": 500000.0,
        "data_files": _write_replay_files(tmp_path),
        "parameter_grid": {
            "ema_fast_periods": [20],
            "ema_slow_periods": [50],
            "rsi_periods": [14],
            "breakout_lookbacks": [20],
            "min_confidence_scores": [60],
            "min_reward_risk_ratios": [1.5],
        },
        "walk_forward_splits": 3,
    }

    import asyncio

    result = asyncio.run(_run_service(service, payload))

    assert result.status == "completed"
    assert len(result.leaderboard) == 1
    assert len(result.leaderboard[0].walk_forward_results) > 0


def test_empty_grid_returns_clean_empty_result(tmp_path: Path) -> None:
    service = _make_service()
    payload = {
        "symbols": ["BTCUSDT"],
        "initial_balance": 500000.0,
        "data_files": _write_replay_files(tmp_path),
        "parameter_grid": {},
    }

    import asyncio

    result = asyncio.run(_run_service(service, payload))

    assert result.status == "empty"
    assert result.evaluated_combinations == 0
    assert result.leaderboard == []

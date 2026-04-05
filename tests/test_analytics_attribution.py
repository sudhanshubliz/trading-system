from __future__ import annotations

from app.analytics.regime import VALID_REGIMES, classify_regime
from tests.test_portfolio_allocator import build_portfolio_env, seed_closed_trade


def test_analytics_strategy_attribution_returns_expected_shape(tmp_path) -> None:
    env = build_portfolio_env(tmp_path)
    seed_closed_trade(
        env,
        trade_id="trd_strategy_001",
        strategy_name="trend_follow_continuation",
        symbol="BTCUSDT",
        realized_pnl=150.0,
    )
    seed_closed_trade(
        env,
        trade_id="trd_strategy_002",
        strategy_name="breakout",
        symbol="ETHUSDT",
        realized_pnl=-50.0,
    )

    payload = env["analytics_service"].get_strategy_attribution()  # type: ignore[index]

    assert payload["count"] == 2
    assert set(payload["items"][0]) == {
        "strategy_name",
        "total_pnl",
        "win_rate",
        "expectancy",
        "drawdown_pct",
        "capital_efficiency",
        "average_holding_minutes",
        "trade_count",
        "contribution_pct",
        "regime_breakdown",
    }


def test_regime_classification_returns_valid_label(tmp_path) -> None:
    env = build_portfolio_env(tmp_path)
    seed_closed_trade(
        env,
        trade_id="trd_regime_001",
        strategy_name="trend_follow_continuation",
        symbol="BTCUSDT",
        realized_pnl=220.0,
    )
    seed_closed_trade(
        env,
        trade_id="trd_regime_002",
        strategy_name="trend_follow_continuation",
        symbol="BTCUSDT",
        realized_pnl=-40.0,
    )

    label = classify_regime(
        env["trades_repo"].list_trades(),  # type: ignore[index]
        volatility_lookback=20,
        trend_lookback=50,
    )

    assert label in VALID_REGIMES

from __future__ import annotations

from pathlib import Path

from tests.test_portfolio_allocator import build_assessment, build_portfolio_env


def test_orchestrator_ranks_and_selects_candidates_deterministically(tmp_path: Path) -> None:
    env = build_portfolio_env(
        tmp_path,
        settings_update={
            "portfolio_max_per_strategy_pct": 100.0,
            "portfolio_max_per_symbol_pct": 100.0,
            "portfolio_max_single_trade_pct": 100.0,
        },
    )
    first = build_assessment(
        assessment_id="ras_btc",
        symbol="BTCUSDT",
        strategy_name="breakout",
        risk_score=88,
        reward_risk=2.0,
        notional_value=300.0,
    )
    second = build_assessment(
        assessment_id="ras_eth",
        symbol="ETHUSDT",
        strategy_name="trend_follow_continuation",
        risk_score=88,
        reward_risk=2.0,
        notional_value=300.0,
    )
    for assessment in (second, first):
        env["risk_repo"].upsert_assessment(assessment)  # type: ignore[index]

    payload = env["portfolio_service"].evaluate_candidates(["ras_eth", "ras_btc"])  # type: ignore[index]
    ordered_ids = [item.assessment_id for item in payload["decisions"]]

    assert ordered_ids == ["ras_btc", "ras_eth"]
    assert payload["selected_count"] == 2


def test_conflicting_candidates_are_rejected_or_deferred(tmp_path: Path) -> None:
    env = build_portfolio_env(
        tmp_path,
        settings_update={
            "portfolio_max_per_strategy_pct": 100.0,
            "portfolio_max_per_symbol_pct": 100.0,
            "portfolio_max_single_trade_pct": 100.0,
        },
    )
    allowed = build_assessment(
        assessment_id="ras_long",
        symbol="BTCUSDT",
        side="long",
        risk_score=95,
        reward_risk=2.5,
        notional_value=200.0,
    )
    blocked = build_assessment(
        assessment_id="ras_short",
        symbol="BTCUSDT",
        side="short",
        risk_score=75,
        reward_risk=1.8,
        notional_value=200.0,
    )
    env["risk_repo"].upsert_assessment(allowed)  # type: ignore[index]
    env["risk_repo"].upsert_assessment(blocked)  # type: ignore[index]

    payload = env["portfolio_service"].evaluate_candidates(["ras_short", "ras_long"])  # type: ignore[index]
    decisions = {item.assessment_id: item for item in payload["decisions"]}

    assert decisions["ras_long"].allowed is True
    assert decisions["ras_short"].allowed is False
    assert "conflicting_symbol_side" in decisions["ras_short"].reasons


def test_portfolio_denial_reason_is_persisted(tmp_path: Path) -> None:
    env = build_portfolio_env(
        tmp_path,
        settings_update={
            "portfolio_max_per_strategy_pct": 0.0,
            "portfolio_max_per_symbol_pct": 100.0,
            "portfolio_max_single_trade_pct": 100.0,
        },
    )
    assessment = build_assessment(
        assessment_id="ras_denied",
        strategy_name="trend_follow_continuation",
        notional_value=100.0,
    )
    env["risk_repo"].upsert_assessment(assessment)  # type: ignore[index]

    payload = env["portfolio_service"].evaluate_candidates(["ras_denied"])  # type: ignore[index]
    records = env["portfolio_repo"].list_records(record_type="portfolio_decision")  # type: ignore[index]

    assert payload["rejected_count"] == 1
    assert any("strategy_cap_exceeded" in record["payload"]["reasons"] for record in records)

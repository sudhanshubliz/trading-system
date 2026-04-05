from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.analytics.service import AnalyticsService
from app.config.settings import get_settings
from app.execution.types import Position, Trade
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.analytics_repo import AnalyticsRepository
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.portfolio_repo import PortfolioRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.risk_repo import RiskRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.portfolio.service import PortfolioService
from app.risk.types import RiskAssessment, RiskCheckResult


def build_assessment(
    *,
    assessment_id: str,
    symbol: str = "BTCUSDT",
    strategy_name: str = "trend_follow_continuation",
    side: str = "long",
    notional_value: float = 100.0,
    risk_score: int = 90,
    reward_risk: float = 2.0,
) -> RiskAssessment:
    entry_price = 100.0
    position_size = notional_value / entry_price
    return RiskAssessment(
        assessment_id=assessment_id,
        signal_id=f"sig_{assessment_id}",
        symbol=symbol,
        side=side,
        strategy_name=strategy_name,
        final_decision="approved_for_review",
        account_balance=10000.0,
        max_risk_pct=2.0,
        risk_amount=50.0,
        stop_distance_abs=5.0,
        stop_distance_pct=5.0,
        position_size=position_size,
        notional_value=notional_value,
        estimated_fee=1.0,
        estimated_slippage_pct=0.0,
        open_risk_pct_before=0.0,
        open_risk_pct_after=0.5,
        daily_drawdown_pct=0.0,
        weekly_drawdown_pct=0.0,
        min_reward_risk_ratio=1.5,
        actual_reward_risk_ratio=reward_risk,
        confidence_threshold=65,
        risk_score=risk_score,
        trade_classification="A+",
        passed_checks_count=10,
        failed_checks_count=0,
        checks=[RiskCheckResult(name="ok", passed=True)],
        rejection_reasons=[],
        generated_trade_plan={
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "stop_loss": 95.0,
            "target_1": 110.0,
            "target_2": 120.0,
            "position_size": position_size,
            "notional_value": notional_value,
            "mode": "paper",
            "approved_for_review": True,
        },
        assessed_at=datetime.now(timezone.utc),
    )


def seed_closed_trade(
    env: dict[str, object],
    *,
    trade_id: str,
    strategy_name: str,
    symbol: str,
    realized_pnl: float,
    execution_mode: str = "paper",
    closed_minutes_ago: int = 60,
) -> None:
    now = datetime.now(timezone.utc)
    env["trades_repo"].upsert_trade(  # type: ignore[index]
        Trade(
            trade_id=trade_id,
            approval_id=f"apr_{trade_id}",
            assessment_id=f"ras_{trade_id}",
            signal_id=f"sig_{trade_id}",
            position_id=f"pos_{trade_id}",
            symbol=symbol,
            side="long",
            strategy_name=strategy_name,
            quantity=1.0,
            execution_price=100.0,
            requested_entry_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=120.0,
            status="FILLED",
            execution_mode=execution_mode,
            opened_at=now - timedelta(hours=3),
            updated_at=now - timedelta(minutes=closed_minutes_ago),
            closed_at=now - timedelta(minutes=closed_minutes_ago),
            realized_pnl=realized_pnl,
        )
    )


def build_portfolio_env(
    tmp_path: Path,
    *,
    settings_update: dict[str, object] | None = None,
) -> dict[str, object]:
    updates = {
        "persistence_enabled": True,
        "persistence_db_url": f"sqlite:///{tmp_path / 'portfolio.db'}",
        "portfolio_enabled": True,
        "portfolio_max_total_capital_pct": 100.0,
        "portfolio_max_per_strategy_pct": 40.0,
        "portfolio_max_per_symbol_pct": 35.0,
        "portfolio_max_open_positions": 5,
        "portfolio_max_correlated_cluster_pct": 60.0,
        "portfolio_max_single_trade_pct": 20.0,
        "portfolio_reserve_cash_pct": 10.0,
        "portfolio_rebalance_enabled": True,
        "analytics_enabled": True,
    }
    updates.update(settings_update or {})
    settings = get_settings().model_copy(update=updates)
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)

    risk_repo = RiskRepository(session_factory)
    approvals_repo = ApprovalsRepository(session_factory)
    positions_repo = PositionsRepository(session_factory)
    trades_repo = TradesRepository(session_factory)
    portfolio_repo = PortfolioRepository(session_factory)
    analytics_repo = AnalyticsRepository(session_factory)
    events_repo = EventsRepository(session_factory)

    portfolio_service = PortfolioService(
        settings=settings,
        risk_repo=risk_repo,
        approvals_repo=approvals_repo,
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        portfolio_repo=portfolio_repo,
        events_repo=events_repo,
    )
    analytics_service = AnalyticsService(
        settings=settings,
        trades_repo=trades_repo,
        analytics_repo=analytics_repo,
    )
    return {
        "settings": settings,
        "risk_repo": risk_repo,
        "approvals_repo": approvals_repo,
        "positions_repo": positions_repo,
        "trades_repo": trades_repo,
        "portfolio_repo": portfolio_repo,
        "analytics_repo": analytics_repo,
        "events_repo": events_repo,
        "portfolio_service": portfolio_service,
        "analytics_service": analytics_service,
    }


def test_allocator_respects_strategy_cap(tmp_path: Path) -> None:
    env = build_portfolio_env(
        tmp_path,
        settings_update={
            "portfolio_max_per_strategy_pct": 20.0,
            "portfolio_max_per_symbol_pct": 100.0,
            "portfolio_max_single_trade_pct": 100.0,
        },
    )
    assessment = build_assessment(
        assessment_id="ras_strategy_cap",
        strategy_name="trend_follow_continuation",
        symbol="BTCUSDT",
        notional_value=3000.0,
    )
    env["risk_repo"].upsert_assessment(assessment)  # type: ignore[index]

    payload = env["portfolio_service"].evaluate_candidates(["ras_strategy_cap"])  # type: ignore[index]
    decision = payload["decisions"][0]

    assert decision.allowed is True
    assert decision.decision == "reduced"
    assert decision.allocated_capital == 2000.0
    assert "strategy_cap_applied" in decision.reasons


def test_allocator_respects_symbol_cap(tmp_path: Path) -> None:
    env = build_portfolio_env(
        tmp_path,
        settings_update={
            "portfolio_max_per_strategy_pct": 100.0,
            "portfolio_max_per_symbol_pct": 15.0,
            "portfolio_max_single_trade_pct": 100.0,
        },
    )
    assessment = build_assessment(
        assessment_id="ras_symbol_cap",
        strategy_name="breakout",
        symbol="BTCUSDT",
        notional_value=2500.0,
    )
    env["risk_repo"].upsert_assessment(assessment)  # type: ignore[index]

    payload = env["portfolio_service"].evaluate_candidates(["ras_symbol_cap"])  # type: ignore[index]
    decision = payload["decisions"][0]

    assert decision.allowed is True
    assert decision.decision == "reduced"
    assert decision.allocated_capital == 1500.0
    assert "symbol_cap_applied" in decision.reasons

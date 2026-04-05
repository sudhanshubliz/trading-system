from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config.settings import get_settings
from app.execution.types import Trade
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.reports_repo import ReportsRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.reporting.aggregator import ReportAggregator
from app.reporting.service import ReportingService


def _build_trade(trade_id: str, *, symbol: str, strategy_name: str, pnl: float, opened_at: datetime, closed_at: datetime) -> Trade:
    return Trade(
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
        status="closed",
        execution_mode="paper",
        opened_at=opened_at,
        updated_at=closed_at,
        closed_at=closed_at,
        realized_pnl=pnl,
    )


def test_reporting_metrics(tmp_path: Path) -> None:
    settings = get_settings().model_copy(
        update={
            "persistence_enabled": True,
            "persistence_db_url": f"sqlite:///{tmp_path / 'reporting.db'}",
        }
    )
    init_persistence_db(settings)
    session_factory = get_persistence_session_factory(settings.persistence_db_url)
    trades_repo = TradesRepository(session_factory)
    reports_repo = ReportsRepository(session_factory)

    base_time = datetime(2026, 4, 3, 10, 0, tzinfo=timezone.utc)
    trades_repo.upsert_trade(
        _build_trade("001", symbol="BTCUSDT", strategy_name="trend_follow_continuation", pnl=10.0, opened_at=base_time, closed_at=base_time + timedelta(minutes=30))
    )
    trades_repo.upsert_trade(
        _build_trade("002", symbol="ETHUSDT", strategy_name="breakout_confirmation", pnl=-5.0, opened_at=base_time + timedelta(days=1), closed_at=base_time + timedelta(days=1, minutes=45))
    )

    service = ReportingService(ReportAggregator(trades_repo), settings=settings, reports_repo=reports_repo)
    daily = service.get_daily_report()
    weekly = service.get_weekly_report()
    strategy = service.get_strategy_report()
    symbol = service.get_symbol_report()

    assert daily["count"] == 2
    assert weekly["count"] >= 1
    assert strategy["count"] == 2
    assert symbol["count"] == 2
    assert daily["items"][0]["total_trades"] == 1
    assert all("net_pnl" in item for item in strategy["items"])

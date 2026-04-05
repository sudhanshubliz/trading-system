from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.execution.types import Trade
from app.live.types import LiveRolloutState
from tests.test_rollout_policy import build_rollout_env


def test_drawdown_trigger_causes_rollback(tmp_path: Path, monkeypatch) -> None:
    env = build_rollout_env(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    env["rollout_repo"].upsert_rollout_state(  # type: ignore[index]
        LiveRolloutState(
            current_phase="scaled",
            current_capital_limit=1000.0,
            allowed_capital_limit=1000.0,
            strategy_allocations={},
            symbol_allocations={},
            last_phase_change_at=now,
            changed_by="test",
            reason="seed_scaled",
            rollback_active=False,
            notes=[],
            updated_at=now,
        )
    )
    env["trades_repo"].upsert_trade(  # type: ignore[index]
        Trade(
            trade_id="trd_loss_001",
            approval_id="apr_loss_001",
            assessment_id="ras_loss_001",
            signal_id="sig_loss_001",
            position_id="pos_loss_001",
            symbol="BTCUSDT",
            side="long",
            strategy_name="trend_follow_continuation",
            quantity=1.0,
            execution_price=100.0,
            requested_entry_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=120.0,
            status="FILLED",
            execution_mode="live",
            opened_at=now - timedelta(days=1),
            updated_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=2),
            realized_pnl=-500.0,
        )
    )
    env["trades_repo"].upsert_trade(  # type: ignore[index]
        Trade(
            trade_id="trd_loss_002",
            approval_id="apr_loss_002",
            assessment_id="ras_loss_002",
            signal_id="sig_loss_002",
            position_id="pos_loss_002",
            symbol="ETHUSDT",
            side="long",
            strategy_name="breakout",
            quantity=1.0,
            execution_price=100.0,
            requested_entry_price=100.0,
            stop_loss=95.0,
            target_1=110.0,
            target_2=120.0,
            status="FILLED",
            execution_mode="live",
            opened_at=now - timedelta(hours=4),
            updated_at=now - timedelta(hours=1),
            closed_at=now - timedelta(hours=1),
            realized_pnl=-500.0,
        )
    )

    state = env["rollout_service"].run_rollout_guardrails(changed_by="system", reason="test_drawdown")  # type: ignore[index]
    events = env["events_repo"].list_events(event_type="rollout_auto_rollback", execution_mode="live")  # type: ignore[index]

    assert state.rollback_active is True
    assert state.current_phase == "disabled"
    assert any(event["event_type"] == "rollout_auto_rollback" for event in events)


def test_rollout_phase_change_persists(tmp_path: Path, monkeypatch) -> None:
    env = build_rollout_env(tmp_path, monkeypatch)

    state = env["rollout_service"].set_rollout_phase("micro", changed_by="test", reason="enable_micro")  # type: ignore[index]
    persisted = env["rollout_repo"].get_rollout_state()  # type: ignore[index]
    history = env["rollout_repo"].list_phase_history()  # type: ignore[index]

    assert state.current_phase == "micro"
    assert persisted is not None
    assert persisted.current_phase == "micro"
    assert any(item.event_type == "rollout_phase_changed" for item in history)

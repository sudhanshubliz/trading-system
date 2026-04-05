from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_rollout_policy import build_rollout_env


def test_scale_up_requires_thresholds(tmp_path: Path, monkeypatch) -> None:
    env = build_rollout_env(tmp_path, monkeypatch)
    env["rollout_service"].set_rollout_phase("micro", changed_by="test", reason="enable_micro")  # type: ignore[index]

    with pytest.raises(ValueError) as exc_info:
        env["rollout_service"].scale_up(changed_by="test", reason="try_scale_up")  # type: ignore[index]

    assert "insufficient_live_trade_count" in str(exc_info.value)

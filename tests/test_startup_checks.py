from __future__ import annotations

import asyncio

from app.config.settings import get_settings
from app.ops.startup_checks import StartupCheckService


def test_startup_checks_detect_missing_critical_config() -> None:
    settings = get_settings().model_copy(
        update={
            "enable_live_trading": True,
            "binance_api_key": "",
            "binance_api_secret": "",
        }
    )
    service = StartupCheckService(
        settings=settings,
        persistence_session_factory=None,
        events_repo=None,
        locks_repo=None,
        live_controller=None,
        persistence_available=False,
        persistence_error="persistence unavailable",
    )

    report = asyncio.run(service.run_checks(write_probe_event=False))

    failed_names = {item.name for item in report.results if item.status == "failed"}
    assert "live_credentials" in failed_names
    assert "live_controller" in failed_names
    assert "live_lock_store" in failed_names

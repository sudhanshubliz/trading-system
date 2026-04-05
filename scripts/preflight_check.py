from __future__ import annotations

import asyncio
import json

from app.config.settings import get_settings
from app.db.session import init_db
from app.execution.live_adapter import BinanceLiveExecutionAdapter
from app.live.controller import LiveController
from app.live.locks import LiveLockManager
from app.ops.startup_checks import StartupCheckService
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.locks_repo import LocksRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.risk_repo import RiskRepository
from app.persistence.repositories.trades_repo import TradesRepository


async def main() -> None:
    settings = get_settings()
    init_db()

    persistence_available = False
    persistence_error: str | None = None
    session_factory = None
    events_repo = None
    locks_repo = None
    live_controller = None

    if settings.persistence_enabled:
        try:
            init_persistence_db(settings)
            session_factory = get_persistence_session_factory(settings.persistence_db_url)
            events_repo = EventsRepository(session_factory)
            locks_repo = LocksRepository(session_factory)
            persistence_available = True
            if settings.enable_live_trading:
                live_controller = LiveController(
                    settings=settings,
                    adapter=BinanceLiveExecutionAdapter(settings=settings),
                    lock_manager=LiveLockManager(locks_repo=locks_repo, events_repo=events_repo),
                    risk_repo=RiskRepository(session_factory),
                    approvals_repo=ApprovalsRepository(session_factory),
                    trades_repo=TradesRepository(session_factory),
                    positions_repo=PositionsRepository(session_factory),
                    events_repo=events_repo,
                )
        except Exception as exc:
            persistence_error = str(exc)
    else:
        persistence_error = "persistence_disabled"

    report = await StartupCheckService(
        settings=settings,
        persistence_session_factory=session_factory,
        events_repo=events_repo,
        locks_repo=locks_repo,
        live_controller=live_controller,
        persistence_available=persistence_available,
        persistence_error=persistence_error,
    ).run_checks(write_probe_event=False)
    print(json.dumps({"status": report.status, "boot_ready": report.boot_ready, "ready": report.ready, "results": [item.__dict__ for item in report.results]}, default=str, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())

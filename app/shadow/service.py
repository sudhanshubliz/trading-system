from __future__ import annotations

from datetime import datetime, timezone

from app.config.settings import Settings, get_settings
from app.execution.service import ExecutionService
from app.shadow.runner import ShadowRunner


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ShadowService:
    def __init__(self, runner: ShadowRunner, *, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.runner = runner

    async def stop(self) -> None:
        await self.runner.stop()

    async def start_shadow(self) -> dict[str, object]:
        await self.runner.start()
        return self.get_status()

    async def stop_shadow(self) -> dict[str, object]:
        await self.runner.stop()
        return self.get_status()

    async def run_cycle(self, symbols: list[str] | None = None) -> None:
        await self.runner.run_cycle(symbols)

    def get_status(self) -> dict[str, object]:
        return {
            "running": self.runner.running,
            "auto_approve": self.runner.auto_approve,
            "execution_mode": "shadow",
            "last_cycle_at": self.runner.last_cycle_at,
            "last_error": self.runner.last_error,
            "blocked_reason": self.runner.blocked_reason,
            "timestamp": utc_now(),
        }

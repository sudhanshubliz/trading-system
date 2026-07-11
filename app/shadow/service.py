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
            "started_at": self.runner.started_at,
            "stopped_at": self.runner.stopped_at,
            "cycle_count": self.runner.cycle_count,
            "last_cycle_at": self.runner.last_cycle_at,
            "last_error": self.runner.last_error,
            "blocked_reason": self.runner.blocked_reason,
            "evidence": self._build_evidence(),
            "timestamp": utc_now(),
        }

    def _build_evidence(self) -> dict[str, object]:
        evidence_start = self.runner.started_at
        trades = [
            item
            for item in self.runner.execution_service.snapshot_recorded_trades()
            if evidence_start is not None
            and item.execution_mode == "shadow"
            and item.opened_at >= evidence_start
        ]
        closed = [item for item in trades if item.status == "closed"]
        evidence_end = self.runner.stopped_at if not self.runner.running and self.runner.stopped_at else utc_now()
        evidence_days = (
            max((evidence_end - evidence_start).total_seconds(), 0.0) / 86400.0
            if evidence_start is not None
            else 0.0
        )
        net_values = [item.realized_pnl for item in closed]
        gross_profit = sum(max(value, 0.0) for value in net_values)
        gross_loss = sum(abs(min(value, 0.0)) for value in net_values)
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        expectancy = sum(net_values) / len(net_values) if net_values else 0.0
        blockers: list[str] = []
        if evidence_days < self.settings.shadow_min_evidence_days:
            blockers.append("shadow_duration_below_minimum")
        if len(closed) < self.settings.shadow_min_closed_trades:
            blockers.append("shadow_closed_trades_below_minimum")
        if expectancy <= self.settings.shadow_min_expectancy:
            blockers.append("shadow_expectancy_not_positive")
        if profit_factor < self.settings.shadow_min_profit_factor:
            blockers.append("shadow_profit_factor_below_minimum")
        if self.runner.last_error:
            blockers.append("shadow_runner_error_present")
        return {
            "stable": not blockers,
            "blockers": blockers,
            "evidence_days": round(evidence_days, 6),
            "minimum_evidence_days": self.settings.shadow_min_evidence_days,
            "cycle_count": self.runner.cycle_count,
            "total_trades": len(trades),
            "closed_trades": len(closed),
            "minimum_closed_trades": self.settings.shadow_min_closed_trades,
            "net_realized_pnl": round(sum(net_values), 6),
            "gross_realized_pnl": round(sum(item.gross_realized_pnl for item in closed), 6),
            "fees_paid": round(sum(item.fees_paid for item in closed), 6),
            "slippage_cost": round(sum(item.slippage_cost for item in closed), 6),
            "expectancy": round(expectancy, 6),
            "profit_factor": round(profit_factor, 6),
            "started_at": evidence_start,
            "evaluated_at": evidence_end,
        }

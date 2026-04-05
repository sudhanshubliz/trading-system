from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone

from app.core.logging import log_structured_event
from app.execution.live_sync import LiveSyncService
from app.live.locks import LiveLockManager
from app.live.types import LiveLockType, LiveReconciliationResult
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.trades_repo import TradesRepository

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveReconciler:
    def __init__(
        self,
        *,
        live_sync: LiveSyncService,
        trades_repo: TradesRepository,
        positions_repo: PositionsRepository,
        lock_manager: LiveLockManager,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.live_sync = live_sync
        self.trades_repo = trades_repo
        self.positions_repo = positions_repo
        self.lock_manager = lock_manager
        self.events_repo = events_repo

    def reconcile(self) -> LiveReconciliationResult:
        timestamp = utc_now()
        mismatches: list[str] = []
        try:
            exchange_orders = self.live_sync.get_open_orders()
            exchange_positions = self.live_sync.get_positions()
        except Exception as exc:
            lock = self.lock_manager.activate_lock(
                LiveLockType.EXCHANGE_SYNC_ERROR,
                reason=f"exchange_sync_failed:{exc}",
                metadata={"error": str(exc)},
            )
            return LiveReconciliationResult(
                ok=False,
                mismatches=[str(exc)],
                activated_lock_id=lock.lock_id,
                timestamp=timestamp,
            )

        live_trades = self.trades_repo.list_trades("live")
        live_positions = self.positions_repo.list_positions("live")
        exchange_order_ids = {item.exchange_order_id for item in exchange_orders if item.exchange_order_id}
        exchange_symbols = {item.symbol for item in exchange_positions}

        for trade in live_trades:
            if trade.status in {"CLOSED", "FAILED", "REJECTED"}:
                continue
            if trade.exchange_order_id and trade.exchange_order_id not in exchange_order_ids:
                mismatches.append(f"missing_exchange_order:{trade.trade_id}")

        for position in live_positions:
            if position.status == "closed":
                continue
            if position.symbol not in exchange_symbols:
                mismatches.append(f"missing_exchange_position:{position.position_id}")
            updated = replace(
                position,
                reconciliation_status="reconciled" if position.symbol in exchange_symbols else "mismatch",
                last_reconciled_at=timestamp,
            )
            self.positions_repo.upsert_position(updated)

        if mismatches:
            lock = self.lock_manager.activate_lock(
                LiveLockType.EXCHANGE_SYNC_ERROR,
                reason="reconciliation_mismatch",
                metadata={"mismatch_count": len(mismatches)},
            )
            if self.events_repo is not None:
                self.events_repo.append_event(
                    event_type="live_reconciliation_mismatch",
                    execution_mode="live",
                    payload={"mismatches": mismatches},
                )
            log_structured_event(logger, "live_reconciliation_mismatch", mismatches=mismatches)
            return LiveReconciliationResult(
                ok=False,
                mismatches=mismatches,
                activated_lock_id=lock.lock_id,
                timestamp=timestamp,
            )

        return LiveReconciliationResult(ok=True, mismatches=[], activated_lock_id=None, timestamp=timestamp)

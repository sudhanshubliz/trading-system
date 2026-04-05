from __future__ import annotations

from app.execution.live_adapter import BinanceLiveExecutionAdapter
from app.live.types import LiveOrderResult


class LiveSyncService:
    def __init__(self, adapter: BinanceLiveExecutionAdapter) -> None:
        self.adapter = adapter

    def get_open_orders(self) -> list[LiveOrderResult]:
        return self.adapter.get_open_orders()

    def get_positions(self):
        return self.adapter.get_positions()

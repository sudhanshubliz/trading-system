from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from app.execution.types import Position, Trade


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def calculate_pnl(side: str, entry_price: float, exit_price: float, quantity: float) -> float:
    if quantity <= 0:
        return 0.0
    if side == "long":
        return (exit_price - entry_price) * quantity
    if side == "short":
        return (entry_price - exit_price) * quantity
    return 0.0


class PositionManager:
    def __init__(self, *, time_provider: Callable[[], datetime] | None = None) -> None:
        self.time_provider = time_provider or utc_now

    def open_position(self, position: Position) -> Position:
        return replace(position)

    def update_market_price(
        self,
        position: Position,
        trade: Trade,
        market_price: float,
    ) -> tuple[Position, Trade]:
        if market_price <= 0:
            return replace(position), replace(trade)

        updated_position = replace(position)
        updated_trade = replace(trade)
        now = self.time_provider()
        updated_position.current_price = market_price
        updated_position.updated_at = now
        updated_trade.updated_at = now

        if updated_position.status == "closed" or updated_position.quantity_open <= 0:
            updated_position.unrealized_pnl = 0.0
            return updated_position, updated_trade

        if self._hit_stop(updated_position, market_price):
            self._close_quantity(updated_position, updated_trade, updated_position.quantity_open, updated_position.stop_loss)
            updated_position.status = "closed"
            updated_position.close_reason = "stop_loss"
            updated_position.closed_at = now
            updated_trade.status = "closed"
            updated_trade.closed_at = now
            updated_position.unrealized_pnl = 0.0
            return updated_position, updated_trade

        if not updated_position.target_1_hit and self._hit_target_1(updated_position, market_price):
            partial_qty = round(updated_position.quantity_open / 2, 6)
            if partial_qty > 0:
                self._close_quantity(updated_position, updated_trade, partial_qty, updated_position.target_1)
                updated_position.target_1_hit = True
                updated_position.status = "partially_closed" if updated_position.quantity_open > 0 else "closed"
                updated_trade.status = updated_position.status

        if updated_position.quantity_open > 0 and self._hit_target_2(updated_position, market_price):
            exit_price = updated_position.target_2 if updated_position.target_2 is not None else market_price
            self._close_quantity(updated_position, updated_trade, updated_position.quantity_open, exit_price)
            updated_position.status = "closed"
            updated_position.close_reason = "target_2"
            updated_position.closed_at = now
            updated_trade.status = "closed"
            updated_trade.closed_at = now

        updated_position.unrealized_pnl = calculate_pnl(
            updated_position.side,
            updated_position.entry_price,
            updated_position.current_price,
            updated_position.quantity_open,
        )
        return updated_position, updated_trade

    def close_position(
        self,
        position: Position,
        trade: Trade,
        exit_price: float,
        reason: str,
    ) -> tuple[Position, Trade]:
        updated_position = replace(position)
        updated_trade = replace(trade)
        if updated_position.status == "closed" or updated_position.quantity_open <= 0:
            return updated_position, updated_trade

        now = self.time_provider()
        self._close_quantity(updated_position, updated_trade, updated_position.quantity_open, exit_price)
        updated_position.current_price = exit_price
        updated_position.unrealized_pnl = 0.0
        updated_position.status = "closed"
        updated_position.close_reason = reason
        updated_position.closed_at = now
        updated_position.updated_at = now
        updated_trade.status = "closed"
        updated_trade.closed_at = now
        updated_trade.updated_at = now
        return updated_position, updated_trade

    def _close_quantity(self, position: Position, trade: Trade, quantity: float, exit_price: float) -> None:
        if quantity <= 0 or position.quantity_open <= 0:
            return

        close_qty = min(quantity, position.quantity_open)
        realized = calculate_pnl(position.side, position.entry_price, exit_price, close_qty)
        position.quantity_open = max(position.quantity_open - close_qty, 0.0)
        position.realized_pnl += realized
        trade.realized_pnl += realized

    def _hit_stop(self, position: Position, market_price: float) -> bool:
        if position.side == "long":
            return market_price <= position.stop_loss
        return market_price >= position.stop_loss

    def _hit_target_1(self, position: Position, market_price: float) -> bool:
        if position.side == "long":
            return market_price >= position.target_1
        return market_price <= position.target_1

    def _hit_target_2(self, position: Position, market_price: float) -> bool:
        if position.target_2 is None:
            return False
        if position.side == "long":
            return market_price >= position.target_2
        return market_price <= position.target_2

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from app.config.settings import Settings, get_settings
from app.execution.costs import apply_exit_slippage, calculate_fee, calculate_prediction_market_fee
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
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        time_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
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
        if updated_position.status == "closed" or updated_position.quantity_open <= 0:
            updated_position.unrealized_pnl = 0.0
            return updated_position, updated_trade

        now = self.time_provider()
        updated_position.current_price = market_price
        updated_position.updated_at = now
        updated_trade.updated_at = now

        if self._hit_stop(updated_position, market_price):
            actual_exit = self._close_quantity(
                updated_position,
                updated_trade,
                updated_position.quantity_open,
                updated_position.stop_loss,
            )
            updated_position.current_price = actual_exit
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
            actual_exit = self._close_quantity(updated_position, updated_trade, updated_position.quantity_open, exit_price)
            updated_position.current_price = actual_exit
            updated_position.status = "closed"
            updated_position.close_reason = "target_2"
            updated_position.closed_at = now
            updated_trade.status = "closed"
            updated_trade.closed_at = now

        updated_position.unrealized_pnl = self._estimate_net_unrealized_pnl(updated_position)
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
        actual_exit = self._close_quantity(updated_position, updated_trade, updated_position.quantity_open, exit_price)
        updated_position.current_price = actual_exit
        updated_position.unrealized_pnl = 0.0
        updated_position.status = "closed"
        updated_position.close_reason = reason
        updated_position.closed_at = now
        updated_position.updated_at = now
        updated_trade.status = "closed"
        updated_trade.closed_at = now
        updated_trade.updated_at = now
        return updated_position, updated_trade

    def _close_quantity(self, position: Position, trade: Trade, quantity: float, exit_price: float) -> float:
        if quantity <= 0 or position.quantity_open <= 0:
            return exit_price

        close_qty = min(quantity, position.quantity_open)
        actual_exit = self._simulated_exit_price(position.side, exit_price)
        gross_realized = calculate_pnl(position.side, position.entry_price, actual_exit, close_qty)
        exit_fee = self._calculate_exit_fee(position, shares=close_qty, price=actual_exit)
        net_realized = gross_realized - exit_fee
        exit_slippage_cost = abs(actual_exit - exit_price) * close_qty
        position.quantity_open = max(position.quantity_open - close_qty, 0.0)
        position.gross_realized_pnl += gross_realized
        trade.gross_realized_pnl += gross_realized
        position.fees_paid += exit_fee
        trade.fees_paid += exit_fee
        position.slippage_cost += exit_slippage_cost
        trade.slippage_cost += exit_slippage_cost
        position.realized_pnl += net_realized
        trade.realized_pnl += net_realized
        return actual_exit

    def _estimate_net_unrealized_pnl(self, position: Position) -> float:
        if position.quantity_open <= 0:
            return 0.0
        projected_exit = self._simulated_exit_price(position.side, position.current_price)
        gross = calculate_pnl(
            position.side,
            position.entry_price,
            projected_exit,
            position.quantity_open,
        )
        projected_fee = self._calculate_exit_fee(
            position,
            shares=position.quantity_open,
            price=projected_exit,
        )
        return gross - projected_fee

    def _simulated_exit_price(self, side: str, exit_price: float) -> float:
        if self.settings.execution_mode not in {"paper", "shadow"}:
            return exit_price
        return apply_exit_slippage(
            exit_price,
            side=side,
            slippage_bps=self.settings.paper_execution_base_slippage_bps,
        )

    def _fee_bps(self) -> float:
        if self.settings.execution_mode not in {"paper", "shadow"}:
            return 0.0
        return self.settings.paper_execution_fee_bps

    def _calculate_exit_fee(self, position: Position, *, shares: float, price: float) -> float:
        if self.settings.execution_mode not in {"paper", "shadow"}:
            return 0.0
        if position.fee_model == "polymarket_probability":
            return calculate_prediction_market_fee(
                shares=shares,
                price=price,
                fee_rate=position.fee_rate,
            )
        return calculate_fee(price * shares, self._fee_bps())

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

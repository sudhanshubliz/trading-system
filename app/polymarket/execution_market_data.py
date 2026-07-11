from __future__ import annotations

from dataclasses import dataclass

from app.market_data.types import OrderBookLevel, OrderBookSnapshot, TickerSnapshot
from app.polymarket.service import PolymarketService


@dataclass(slots=True, frozen=True)
class PolymarketExecutionTarget:
    execution_symbol: str
    market_id: str
    outcome: str


class PolymarketExecutionMarketDataAdapter:
    """Read-only outcome-book adapter for the shared risk and paper engines."""

    def __init__(self, service: PolymarketService) -> None:
        self.service = service

    def supports_symbol(self, symbol: str) -> bool:
        return self.service.resolve_execution_symbol(symbol) is not None

    async def get_snapshot(self, symbol: str) -> TickerSnapshot | None:
        target = self.service.resolve_execution_symbol(symbol)
        if target is None:
            return None
        orderbook = await self.service.get_orderbook(target.market_id)
        if orderbook is None:
            return None
        bids, asks = _selected_levels(orderbook, target.outcome)
        bid = bids[0] if bids else None
        ask = asks[0] if asks else None
        midpoint = ((bid.price + ask.price) / 2.0) if bid is not None and ask is not None else ask.price if ask is not None else bid.price if bid is not None else None
        spread_bps = None
        if bid is not None and ask is not None and midpoint and midpoint > 0:
            spread_bps = ((ask.price - bid.price) / midpoint) * 10000.0
        return TickerSnapshot(
            symbol=target.execution_symbol,
            last_price=midpoint,
            bid_price=bid.price if bid is not None else None,
            ask_price=ask.price if ask is not None else None,
            best_bid_qty=bid.quantity if bid is not None else None,
            best_ask_qty=ask.quantity if ask is not None else None,
            spread_bps=spread_bps,
            ws_status="ok" if orderbook.source == "clob_websocket" else "degraded",
            rest_status="ok",
            fallback_active=orderbook.source != "clob_websocket",
            ticker_updated_at=orderbook.captured_at,
            orderbook_updated_at=orderbook.captured_at,
            snapshot_time=orderbook.captured_at,
        )

    async def get_order_book(self, symbol: str) -> OrderBookSnapshot | None:
        target = self.service.resolve_execution_symbol(symbol)
        if target is None:
            return None
        orderbook = await self.service.get_orderbook(target.market_id)
        if orderbook is None:
            return None
        bids, asks = _selected_levels(orderbook, target.outcome)
        return OrderBookSnapshot(
            symbol=target.execution_symbol,
            bids=bids,
            asks=asks,
            updated_at=orderbook.captured_at,
        )

    async def get_health(self, symbol: str | None = None) -> dict[str, object]:
        return await self.service.get_provider_health()


class CompositeExecutionMarketDataService:
    def __init__(self, *, primary: object, polymarket: PolymarketExecutionMarketDataAdapter) -> None:
        self.primary = primary
        self.polymarket = polymarket

    async def get_snapshot(self, symbol: str):
        if self.polymarket.supports_symbol(symbol):
            return await self.polymarket.get_snapshot(symbol)
        return await self.primary.get_snapshot(symbol)

    async def get_order_book(self, symbol: str):
        if self.polymarket.supports_symbol(symbol):
            return await self.polymarket.get_order_book(symbol)
        return await self.primary.get_order_book(symbol)

    async def get_health(self, symbol: str | None = None):
        if symbol is not None and self.polymarket.supports_symbol(symbol):
            return await self.polymarket.get_health(symbol)
        return await self.primary.get_health()

    def __getattr__(self, name: str):
        return getattr(self.primary, name)


def _selected_levels(orderbook, outcome: str) -> tuple[list[OrderBookLevel], list[OrderBookLevel]]:
    normalized = outcome.upper()
    source_bids = orderbook.yes_bids if normalized == "YES" else orderbook.no_bids
    source_asks = orderbook.yes_asks if normalized == "YES" else orderbook.no_asks
    bids = [OrderBookLevel(price=item.price, quantity=item.size) for item in source_bids]
    asks = [OrderBookLevel(price=item.price, quantity=item.size) for item in source_asks]
    return bids, asks

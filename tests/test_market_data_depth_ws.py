from __future__ import annotations

from app.config.settings import Settings
from app.market_data.service import MarketDataService


async def _noop_persist(*args, **kwargs) -> None:
    return None


def test_partial_depth_stream_updates_orderbook(monkeypatch) -> None:
    import asyncio

    settings = Settings(
        MARKET_DATA_SYMBOLS="BTCUSDT,ETHUSDT",
        MARKET_DATA_TIMEFRAMES="5m,15m,1h",
        MARKET_DATA_ENABLED=True,
    )
    service = MarketDataService(settings=settings)
    monkeypatch.setattr(service, "_persist_snapshot_if_due", _noop_persist)

    message = {
        "stream": "btcusdt@depth5@100ms",
        "data": {
            "lastUpdateId": 123456789,
            "bids": [["68000.10", "1.25"]],
            "asks": [["68000.20", "0.75"]],
        },
    }

    asyncio.run(service._handle_ws_message(message))

    order_book = service.orderbook_cache.get("BTCUSDT")
    snapshot = asyncio.run(service.get_snapshot("BTCUSDT"))

    assert order_book is not None
    assert order_book.bid_price == 68000.10
    assert order_book.ask_price == 68000.20
    assert order_book.best_bid_qty == 1.25
    assert order_book.best_ask_qty == 0.75

    assert snapshot is not None
    assert snapshot.bid_price == 68000.10
    assert snapshot.ask_price == 68000.20
    assert snapshot.ws_status == "ok"

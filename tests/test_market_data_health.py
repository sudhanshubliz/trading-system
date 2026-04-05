from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient


class FakeMarketDataService:
    async def get_health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "websocket_status": "ok",
            "fallback_active": False,
            "supported_symbols": ["BTCUSDT", "ETHUSDT"],
            "supported_timeframes": ["5m", "15m", "1h"],
            "last_ws_message_at": datetime(2026, 4, 2, 15, 10, tzinfo=timezone.utc),
            "symbols": {
                "BTCUSDT": {
                    "symbol": "BTCUSDT",
                    "ticker_fresh": True,
                    "orderbook_fresh": True,
                    "candles_fresh": {"5m": True, "15m": True, "1h": True},
                    "last_price": 68250.5,
                    "ticker_updated_at": datetime(2026, 4, 2, 15, 9, 58, tzinfo=timezone.utc),
                    "orderbook_updated_at": datetime(2026, 4, 2, 15, 9, 59, tzinfo=timezone.utc),
                }
            },
            "timestamp": datetime(2026, 4, 2, 15, 10, tzinfo=timezone.utc),
        }


def test_market_data_health_endpoint() -> None:
    from app.main import app

    client = TestClient(app)
    app.state.market_data_service = FakeMarketDataService()

    response = client.get("/api/v1/market-data/health")

    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["websocket_status"] == "ok"
    assert payload["supported_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["symbols"]["BTCUSDT"]["ticker_fresh"] is True

    client.close()

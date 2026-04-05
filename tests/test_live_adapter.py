from __future__ import annotations

import httpx
import pytest

from app.config.settings import get_settings
from app.execution.live_adapter import BinanceLiveExecutionAdapter, LiveAdapterError
from app.live.types import LiveOrderRequest


def test_live_adapter_request_serialization() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "symbol": "BTCUSDT",
                "orderId": 12345,
                "clientOrderId": request.url.params["newClientOrderId"],
                "status": "NEW",
                "side": request.url.params["side"],
                "type": request.url.params["type"],
                "origQty": request.url.params["quantity"],
                "price": request.url.params["price"],
            },
        )

    settings = get_settings().model_copy(
        update={
            "enable_live_trading": True,
            "binance_api_key": "key",
            "binance_api_secret": "secret",
            "live_allow_limit_orders": True,
            "live_allow_market_orders": False,
        }
    )
    client = httpx.Client(
        base_url=settings.binance_base_url,
        transport=httpx.MockTransport(handler),
    )
    adapter = BinanceLiveExecutionAdapter(settings=settings, client=client)

    result = adapter.place_order(
        LiveOrderRequest(
            assessment_id="ras_live_adapter_001",
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.25,
            order_type="LIMIT",
            limit_price=100.5,
            stop_loss=99.0,
            notional=25.125,
            client_order_id="live_order_001",
        )
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v3/order"
    params = captured["params"]
    assert params["symbol"] == "BTCUSDT"
    assert params["side"] == "BUY"
    assert params["type"] == "LIMIT"
    assert params["newClientOrderId"] == "live_order_001"
    assert params["price"] == "100.5"
    assert "signature" in params
    assert result.client_order_id == "live_order_001"
    assert result.exchange_order_id == "12345"
    assert result.status == "NEW"


def test_live_adapter_error_mapping() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -1013, "msg": "invalid quantity"})

    settings = get_settings().model_copy(
        update={
            "enable_live_trading": True,
            "binance_api_key": "key",
            "binance_api_secret": "secret",
        }
    )
    client = httpx.Client(
        base_url=settings.binance_base_url,
        transport=httpx.MockTransport(handler),
    )
    adapter = BinanceLiveExecutionAdapter(settings=settings, client=client)

    with pytest.raises(LiveAdapterError):
        adapter.ping()

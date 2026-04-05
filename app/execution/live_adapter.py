from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config.settings import Settings, get_settings
from app.live.guardrails import normalize_order_side, safe_float
from app.live.types import LiveOrderRequest, LiveOrderResult

logger = logging.getLogger(__name__)


class LiveAdapterError(RuntimeError):
    pass


@dataclass(slots=True)
class ExchangePosition:
    symbol: str
    quantity: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float


class BinanceLiveExecutionAdapter:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or httpx.Client(
            base_url=self.settings.binance_base_url,
            timeout=self.settings.binance_order_timeout_sec,
        )

    def ping(self) -> dict[str, str]:
        self._ensure_live_enabled()
        response = self.client.get("/api/v3/ping")
        self._raise_for_status(response)
        return {"status": "ok"}

    def place_order(self, payload: LiveOrderRequest, *, snapshot: Any | None = None) -> LiveOrderResult:
        self._ensure_live_enabled()
        order_type = payload.order_type.upper()
        if order_type == "MARKET" and not self.settings.live_allow_market_orders:
            raise LiveAdapterError("market_orders_disabled")
        if order_type == "LIMIT" and not self.settings.live_allow_limit_orders:
            raise LiveAdapterError("limit_orders_disabled")
        if safe_float(payload.notional) > self.settings.live_max_order_notional:
            raise LiveAdapterError("order_notional_exceeds_limit")

        params = {
            "symbol": payload.symbol.upper(),
            "side": normalize_order_side(payload.side),
            "type": order_type,
            "quantity": self._format_decimal(payload.quantity),
            "newClientOrderId": payload.client_order_id,
        }
        if order_type == "LIMIT":
            params["timeInForce"] = "GTC"
            params["price"] = self._format_decimal(payload.limit_price)
        signed_response = self._signed_post("/api/v3/order", params)
        return self._parse_order_response(
            signed_response.json(),
            fallback_client_order_id=payload.client_order_id,
            fallback_symbol=payload.symbol,
            fallback_side=normalize_order_side(payload.side),
            order_type=order_type,
            quantity=payload.quantity,
            limit_price=payload.limit_price,
        )

    def cancel_order(self, payload: dict[str, Any]) -> LiveOrderResult:
        self._ensure_live_enabled()
        params = {
            "symbol": str(payload.get("symbol", "")).upper(),
            "orderId": payload.get("exchange_order_id"),
            "origClientOrderId": payload.get("client_order_id"),
        }
        response = self._signed_delete("/api/v3/order", params)
        return self._parse_order_response(
            response.json(),
            fallback_client_order_id=str(payload.get("client_order_id") or ""),
            fallback_symbol=params["symbol"],
            fallback_side=str(payload.get("side") or "BUY"),
            order_type=str(payload.get("order_type") or "LIMIT"),
            quantity=safe_float(payload.get("quantity")),
            limit_price=safe_float(payload.get("limit_price")),
        )

    def get_order(self, *, symbol: str, exchange_order_id: str | None = None, client_order_id: str | None = None) -> LiveOrderResult:
        self._ensure_live_enabled()
        params = {"symbol": symbol.upper()}
        if exchange_order_id is not None:
            params["orderId"] = exchange_order_id
        if client_order_id is not None:
            params["origClientOrderId"] = client_order_id
        response = self._signed_get("/api/v3/order", params)
        return self._parse_order_response(
            response.json(),
            fallback_client_order_id=client_order_id or "",
            fallback_symbol=symbol.upper(),
            fallback_side="BUY",
            order_type="LIMIT",
            quantity=0.0,
            limit_price=None,
        )

    def get_open_orders(self) -> list[LiveOrderResult]:
        self._ensure_live_enabled()
        response = self._signed_get("/api/v3/openOrders", {})
        return [
            self._parse_order_response(
                item,
                fallback_client_order_id=str(item.get("clientOrderId", "")),
                fallback_symbol=str(item.get("symbol", "")),
                fallback_side=str(item.get("side", "BUY")),
                order_type=str(item.get("type", "LIMIT")),
                quantity=safe_float(item.get("origQty")),
                limit_price=safe_float(item.get("price")),
            )
            for item in response.json()
        ]

    def get_positions(self) -> list[ExchangePosition]:
        self._ensure_live_enabled()
        response = self._signed_get("/api/v3/account", {})
        payload = response.json()
        positions: list[ExchangePosition] = []
        for item in payload.get("balances", []):
            quantity = safe_float(item.get("free")) + safe_float(item.get("locked"))
            if quantity <= 0:
                continue
            positions.append(
                ExchangePosition(
                    symbol=f"{item.get('asset', '')}USDT",
                    quantity=quantity,
                    entry_price=0.0,
                    mark_price=0.0,
                    unrealized_pnl=0.0,
                )
            )
        return positions

    def _signed_get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        return self._signed_request("GET", path, params)

    def _signed_post(self, path: str, params: dict[str, Any]) -> httpx.Response:
        return self._signed_request("POST", path, params)

    def _signed_delete(self, path: str, params: dict[str, Any]) -> httpx.Response:
        return self._signed_request("DELETE", path, params)

    def _signed_request(self, method: str, path: str, params: dict[str, Any]) -> httpx.Response:
        self._ensure_credentials()
        signed_params = dict(params)
        signed_params["timestamp"] = int(time.time() * 1000)
        query = urlencode({key: value for key, value in signed_params.items() if value not in (None, "")})
        signature = hmac.new(
            self.settings.binance_api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params["signature"] = signature
        headers = {"X-MBX-APIKEY": self.settings.binance_api_key}
        response = self.client.request(method, path, params=signed_params, headers=headers)
        self._raise_for_status(response)
        return response

    def _parse_order_response(
        self,
        payload: dict[str, Any],
        *,
        fallback_client_order_id: str,
        fallback_symbol: str,
        fallback_side: str,
        order_type: str,
        quantity: float,
        limit_price: float | None,
    ) -> LiveOrderResult:
        return LiveOrderResult(
            client_order_id=str(payload.get("clientOrderId") or fallback_client_order_id),
            exchange_order_id=str(payload.get("orderId")) if payload.get("orderId") is not None else None,
            status=str(payload.get("status") or "UNKNOWN"),
            symbol=str(payload.get("symbol") or fallback_symbol),
            side=str(payload.get("side") or fallback_side),
            order_type=str(payload.get("type") or order_type),
            quantity=safe_float(payload.get("origQty") or quantity),
            limit_price=safe_float(payload.get("price")) if payload.get("price") not in (None, "") else limit_price,
            executed_price=safe_float(payload.get("price")) if payload.get("price") not in (None, "") else limit_price,
            message=str(payload.get("msg")) if payload.get("msg") is not None else None,
            raw_status=str(payload.get("status")) if payload.get("status") is not None else None,
        )

    def _format_decimal(self, value: float | None) -> str:
        numeric = safe_float(value)
        if numeric <= 0:
            raise LiveAdapterError("invalid_decimal_value")
        return f"{numeric:.8f}".rstrip("0").rstrip(".")

    def _ensure_live_enabled(self) -> None:
        if not self.settings.enable_live_trading:
            raise LiveAdapterError("live_trading_disabled")

    def _ensure_credentials(self) -> None:
        if not self.settings.binance_api_key or not self.settings.binance_api_secret:
            raise LiveAdapterError("binance_credentials_missing")

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception("live_adapter_http_error")
            raise LiveAdapterError(str(exc)) from exc


LiveExecutionAdapter = BinanceLiveExecutionAdapter

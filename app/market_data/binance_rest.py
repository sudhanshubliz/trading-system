from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BinanceRestError(Exception):
    pass


class BinanceRestClient:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout, connect=timeout),
        )

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning("binance rest timeout path=%s params=%s", path, params)
            raise BinanceRestError("Binance REST request timed out") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "binance rest http error path=%s status=%s body=%s",
                path,
                exc.response.status_code,
                exc.response.text,
            )
            raise BinanceRestError("Binance REST request failed") from exc
        except httpx.HTTPError as exc:
            logger.warning("binance rest transport error path=%s params=%s", path, params)
            raise BinanceRestError("Binance REST transport error") from exc

        return response.json()

    async def get_exchange_info(self) -> dict[str, Any]:
        payload = await self._get("/api/v3/exchangeInfo", params={})
        if not isinstance(payload, dict):
            raise BinanceRestError("Unexpected exchange info response")
        return payload

    async def get_ticker_price(self, symbol: str) -> dict[str, Any]:
        payload = await self._get("/api/v3/ticker/price", params={"symbol": symbol.upper()})
        if not isinstance(payload, dict):
            raise BinanceRestError("Unexpected ticker price response")
        return payload

    async def get_24hr_ticker(self, symbol: str) -> dict[str, Any]:
        payload = await self._get("/api/v3/ticker/24hr", params={"symbol": symbol.upper()})
        if not isinstance(payload, dict):
            raise BinanceRestError("Unexpected 24hr ticker response")
        return payload

    async def get_order_book(self, symbol: str, limit: int = 5) -> dict[str, Any]:
        payload = await self._get(
            "/api/v3/depth",
            params={"symbol": symbol.upper(), "limit": limit},
        )
        if not isinstance(payload, dict):
            raise BinanceRestError("Unexpected order book response")
        return payload

    async def get_klines(self, symbol: str, interval: str, limit: int = 300) -> list[list[Any]]:
        payload = await self._get(
            "/api/v3/klines",
            params={"symbol": symbol.upper(), "interval": interval.lower(), "limit": limit},
        )
        if not isinstance(payload, list):
            raise BinanceRestError("Unexpected klines response")
        return payload

    async def close(self) -> None:
        await self._client.aclose()

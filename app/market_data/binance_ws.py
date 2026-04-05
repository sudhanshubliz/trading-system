from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


class BinanceWebSocketClient:
    def __init__(self, base_url: str, symbols: list[str], timeframes: list[str]) -> None:
        self._base_url = base_url.rstrip("/")
        self._symbols = [symbol.upper() for symbol in symbols]
        self._timeframes = [timeframe.lower() for timeframe in timeframes]
        self._stop_event = asyncio.Event()
        self._connection: Any | None = None
        self.last_message_at: datetime | None = None
        self.status: str = "stopped"

    def _build_streams(self) -> list[str]:
        streams: list[str] = []
        for symbol in self._symbols:
            stream_symbol = symbol.lower()
            streams.append(f"{stream_symbol}@miniTicker")
            streams.append(f"{stream_symbol}@depth5@100ms")
            for timeframe in self._timeframes:
                streams.append(f"{stream_symbol}@kline_{timeframe}")
        return streams

    def build_url(self) -> str:
        stream_path = "/".join(self._build_streams())
        return f"{self._base_url}?streams={stream_path}"

    async def start(self, message_handler: MessageHandler) -> None:
        retry_delay = 1.0
        max_retry_delay = 10.0
        self._stop_event.clear()

        while not self._stop_event.is_set():
            url = self.build_url()
            self.status = "connecting"
            try:
                logger.info("connecting binance websocket url=%s", url)
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**20,
                ) as websocket:
                    self._connection = websocket
                    self.status = "ok"
                    retry_delay = 1.0
                    logger.info("binance websocket connected")

                    async for raw_message in websocket:
                        if self._stop_event.is_set():
                            break

                        self.last_message_at = utc_now()
                        try:
                            payload = json.loads(raw_message)
                        except json.JSONDecodeError:
                            logger.warning("binance websocket received invalid json")
                            continue

                        await message_handler(payload)
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                self.status = "degraded"
                logger.warning("binance websocket disconnected error=%s", exc)
            finally:
                self._connection = None

            if self._stop_event.is_set():
                break

            logger.info("retrying binance websocket in %.1f seconds", retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)

        self.status = "stopped"
        logger.info("binance websocket stopped")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._connection is not None:
            await self._connection.close()

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.polymarket.types import PolymarketMarket


@dataclass(slots=True)
class LatencyArbMarketMapping:
    market_id: str
    market_title: str
    symbol: str
    direction: str
    threshold: float | None
    close_time: datetime | None


_PRICE_RE = re.compile(r"(?:\\$|above\\s|over\\s|below\\s|under\\s)?([0-9]{2,3}(?:[,][0-9]{3})*(?:\\.[0-9]+)?)", re.IGNORECASE)


def map_market(market: PolymarketMarket) -> LatencyArbMarketMapping | None:
    title = market.title.lower()
    symbol = "BTCUSDT" if "btc" in title or "bitcoin" in title else "ETHUSDT" if "eth" in title or "ethereum" in title else ""
    if not symbol:
        return None
    direction = "up"
    if any(token in title for token in ("below", "under", "falls", "drop", "down")):
        direction = "down"
    threshold = None
    matches = _PRICE_RE.findall(title.replace("k", "000"))
    if matches:
        raw = matches[-1].replace(",", "")
        try:
            threshold = float(raw)
        except ValueError:
            threshold = None
    metadata_threshold = market.metadata.get("threshold_price") if isinstance(market.metadata, dict) else None
    if threshold is None and metadata_threshold is not None:
        try:
            threshold = float(metadata_threshold)
        except (TypeError, ValueError):
            threshold = None
    return LatencyArbMarketMapping(
        market_id=market.market_id,
        market_title=market.title,
        symbol=symbol,
        direction=direction,
        threshold=threshold,
        close_time=market.close_time,
    )

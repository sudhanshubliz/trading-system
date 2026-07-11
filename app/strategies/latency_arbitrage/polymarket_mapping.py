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
    start_time: datetime | None = None
    duration_minutes: int | None = None
    outcome_name: str = "YES"
    mapping_confidence: float = 0.0
    resolution_source: str | None = None


_PRICE_RE = re.compile(
    r"(?:\$|above\s+|over\s+|below\s+|under\s+)([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,6})(?:\.[0-9]+)?",
    re.IGNORECASE,
)
_K_PRICE_RE = re.compile(
    r"(?:\$|above\s+|over\s+|below\s+|under\s+)([0-9]+(?:\.[0-9]+)?)\s*k\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(r"\b(5|15)\s*(?:m|min|minute|minutes)\b", re.IGNORECASE)


def map_market(market: PolymarketMarket) -> LatencyArbMarketMapping | None:
    context = f"{market.title} {market.event_slug} {market.metadata.get('series_slug', '')}".lower()
    symbol = (
        "BTCUSDT"
        if "btc" in context or "bitcoin" in context
        else "ETHUSDT"
        if "eth" in context or "ethereum" in context
        else ""
    )
    if not symbol:
        return None

    direction = "up"
    if any(token in context for token in ("below", "under", "falls", "drop", "down")) and "up or down" not in context:
        direction = "down"

    threshold = _explicit_threshold(market)
    start_time = market.metadata.get("start_time") if isinstance(market.metadata, dict) else None
    if not isinstance(start_time, datetime):
        start_time = None
    duration_minutes = _duration_minutes(market, context)
    diagnostics = market.metadata.get("diagnostics", {}) if isinstance(market.metadata, dict) else {}
    outcomes = diagnostics.get("outcomes", []) if isinstance(diagnostics, dict) else []
    outcome_name = str(outcomes[0]).upper() if isinstance(outcomes, list) and outcomes else "YES"
    mapping_confidence = 1.0 if threshold is not None else 0.55 if start_time is not None else 0.25

    return LatencyArbMarketMapping(
        market_id=market.market_id,
        market_title=market.title,
        symbol=symbol,
        direction=direction,
        threshold=threshold,
        close_time=market.close_time,
        start_time=start_time,
        duration_minutes=duration_minutes,
        outcome_name=outcome_name,
        mapping_confidence=mapping_confidence,
        resolution_source=str(market.metadata.get("resolution_source") or "") or None,
    )


def _explicit_threshold(market: PolymarketMarket) -> float | None:
    matches = _PRICE_RE.findall(market.title)
    if matches:
        try:
            return float(matches[-1].replace(",", ""))
        except ValueError:
            pass
    k_matches = _K_PRICE_RE.findall(market.title)
    if k_matches:
        try:
            return float(k_matches[-1]) * 1000.0
        except ValueError:
            pass
    metadata_threshold = market.metadata.get("threshold_price") if isinstance(market.metadata, dict) else None
    try:
        return float(metadata_threshold) if metadata_threshold is not None else None
    except (TypeError, ValueError):
        return None


def _duration_minutes(market: PolymarketMarket, context: str) -> int | None:
    duration_value = market.metadata.get("duration_minutes") if isinstance(market.metadata, dict) else None
    try:
        if duration_value is not None:
            return int(round(float(duration_value)))
    except (TypeError, ValueError):
        pass
    match = _DURATION_RE.search(context)
    return int(match.group(1)) if match else None

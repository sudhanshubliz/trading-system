from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from xml.etree import ElementTree

import httpx

from app.config.settings import Settings, get_settings
from app.providers.common import (
    ExistingAsyncClientContext,
    FallbackProviderAdapter,
    ProviderRuntimeState,
    ensure_datetime,
    local_fallback_allowed,
    safe_float,
    utc_now,
)


class MockEventProvider:
    def __init__(self) -> None:
        now = utc_now()
        self._events = [
            {
                "event_id": "evt_fed_hold",
                "source": "mock_news",
                "title": "Central bank expected to hold rates",
                "summary": "Markets price low near-term policy surprise risk.",
                "category": "macro",
                "event_type": "macro_calendar",
                "event_time": now + timedelta(hours=2),
                "detection_time": now - timedelta(minutes=15),
                "entities": ["BTCUSDT", "pm_rate_cut_yes"],
                "importance_score": 0.82,
                "sentiment_score": -0.1,
                "relevance_score": 0.74,
                "metadata": {"provider_mode": "mock"},
            },
            {
                "event_id": "evt_crypto_etf",
                "source": "mock_news",
                "title": "ETF approval chatter accelerates",
                "summary": "Prediction markets and crypto assets respond positively.",
                "category": "crypto",
                "event_type": "headline",
                "event_time": now - timedelta(minutes=30),
                "detection_time": now - timedelta(minutes=20),
                "entities": ["BTCUSDT", "pm_crypto_etf_approval"],
                "importance_score": 0.76,
                "sentiment_score": 0.55,
                "relevance_score": 0.81,
                "metadata": {"provider_mode": "mock"},
            },
        ]

    async def list_events(self) -> list[dict[str, object]]:
        return list(self._events)

    async def get_event(self, event_id: str) -> dict[str, object] | None:
        return next((item for item in self._events if item["event_id"] == event_id), None)

    async def search_news(self, query: str) -> list[dict[str, object]]:
        return [item for item in self._events if query.lower() in item["title"].lower()]

    async def fetch_recent_headlines(self) -> list[dict[str, object]]:
        return list(self._events)

    async def fetch_sentiment_signals(self) -> list[dict[str, object]]:
        return [{"event_id": item["event_id"], "sentiment_score": item["sentiment_score"]} for item in self._events]

    async def fetch_macro_calendar(self) -> list[dict[str, object]]:
        return [item for item in self._events if item["category"] == "macro"]

    async def health_check(self) -> dict[str, object]:
        return {"status": "healthy", "success_rate": 1.0, "stale_data_flag": False, "error_count": 0}


class RealEventProvider:
    def __init__(self, *, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._events: dict[str, dict[str, object]] = {}
        self._runtime = ProviderRuntimeState()

    @property
    def has_successful_fetch(self) -> bool:
        return self._runtime.has_successful_fetch

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.event_news_feed_urls
            or self.settings.event_sentiment_feed_url
            or self.settings.event_calendar_feed_url
            or self.settings.event_custom_feed_url
        )

    async def list_events(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        items.extend(await self.fetch_recent_headlines())
        items.extend(await self.fetch_macro_calendar())
        items.extend(await self._fetch_custom_events())
        deduped: dict[str, dict[str, object]] = {}
        for item in items:
            deduped[str(item["event_id"])] = item
        self._events.update(deduped)
        return list(deduped.values())

    async def get_event(self, event_id: str) -> dict[str, object] | None:
        if event_id in self._events:
            return dict(self._events[event_id])
        for item in await self.list_events():
            if item["event_id"] == event_id:
                return item
        return None

    async def search_news(self, query: str) -> list[dict[str, object]]:
        query_lower = query.lower()
        return [item for item in await self.fetch_recent_headlines() if query_lower in str(item["title"]).lower()]

    async def fetch_recent_headlines(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for url in self.settings.event_news_feed_urls:
            content, content_type = await self._request_content(url)
            items.extend(self._normalize_feed(url=url, content=content, content_type=content_type, category="headline"))
        return items

    async def fetch_sentiment_signals(self) -> list[dict[str, object]]:
        if not self.settings.event_sentiment_feed_url:
            return []
        payload = await self._request_json_url(self.settings.event_sentiment_feed_url)
        records = payload if isinstance(payload, list) else payload.get("signals") or payload.get("items") or payload.get("data") or []
        items: list[dict[str, object]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            event_id = str(record.get("event_id") or record.get("headline_id") or "")
            if not event_id:
                continue
            items.append(
                {
                    "event_id": event_id,
                    "sentiment_score": safe_float(record.get("sentiment_score") or record.get("score"), 0.0) or 0.0,
                    "source": "sentiment_feed",
                }
            )
        return items

    async def fetch_macro_calendar(self) -> list[dict[str, object]]:
        if not self.settings.event_calendar_feed_url:
            return []
        payload = await self._request_json_url(self.settings.event_calendar_feed_url)
        records = payload if isinstance(payload, list) else payload.get("events") or payload.get("items") or payload.get("data") or []
        items: list[dict[str, object]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            items.append(self._normalize_json_event(record, source="macro_calendar", default_type="macro_calendar"))
        return items

    async def health_check(self) -> dict[str, object]:
        return self._runtime.build_health(
            max_data_age_seconds=self.settings.event_max_data_age_seconds,
            metadata={
                "provider_mode": "real",
                "news_feed_count": len(self.settings.event_news_feed_urls),
                "calendar_configured": bool(self.settings.event_calendar_feed_url),
                "sentiment_configured": bool(self.settings.event_sentiment_feed_url),
            },
            configured=self.is_configured,
        )

    def should_fallback_on_empty(self, method_name: str, value: object) -> bool:
        return not self.is_configured

    async def _fetch_custom_events(self) -> list[dict[str, object]]:
        if not self.settings.event_custom_feed_url:
            return []
        payload = await self._request_json_url(self.settings.event_custom_feed_url)
        records = payload if isinstance(payload, list) else payload.get("events") or payload.get("items") or payload.get("data") or []
        return [
            self._normalize_json_event(record, source="custom_event_feed", default_type="custom_feed")
            for record in records
            if isinstance(record, dict)
        ]

    async def _request_json_url(self, url: str) -> Any:
        content, _ = await self._request_content(url)
        return json.loads(content.decode("utf-8"))

    async def _request_content(self, url: str) -> tuple[bytes, str]:
        started_at = utc_now()
        try:
            async with self._get_client() as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
                content_type = response.headers.get("content-type", "")
            self._runtime.record_success(started_at=started_at)
            return content, content_type
        except Exception:
            self._runtime.record_failure()
            raise

    def _get_client(self):
        if self._client is not None:
            return ExistingAsyncClientContext(self._client)
        return httpx.AsyncClient(timeout=max(self.settings.event_provider_timeout_ms / 1000.0, 0.5))

    def _normalize_feed(self, *, url: str, content: bytes, content_type: str, category: str) -> list[dict[str, object]]:
        if "json" in content_type:
            payload = json.loads(content.decode("utf-8"))
            records = payload if isinstance(payload, list) else payload.get("items") or payload.get("articles") or payload.get("data") or []
            return [
                self._normalize_json_event(item, source=url, default_type=category)
                for item in records
                if isinstance(item, dict)
            ]
        root = ElementTree.fromstring(content)
        items: list[dict[str, object]] = []
        for entry in root.findall(".//item") + root.findall(".//entry"):
            title = (entry.findtext("title") or "").strip()
            summary = (entry.findtext("description") or entry.findtext("summary") or "").strip()
            link = (entry.findtext("link") or "").strip()
            published = ensure_datetime(entry.findtext("pubDate") or entry.findtext("published") or entry.findtext("updated")) or utc_now()
            event_id = self._build_event_id(url, title, published)
            items.append(
                {
                    "event_id": event_id,
                    "source": url,
                    "title": title,
                    "summary": summary,
                    "category": category,
                    "event_type": category,
                    "event_time": published,
                    "detection_time": published,
                    "entities": self._infer_entities(f"{title} {summary}"),
                    "importance_score": self._importance_from_text(title, summary),
                    "sentiment_score": None,
                    "relevance_score": self._relevance_from_entities(self._infer_entities(f"{title} {summary}")),
                    "metadata": {"link": link, "provider_mode": "real"},
                }
            )
        return items

    def _normalize_json_event(self, raw: dict[str, object], *, source: str, default_type: str) -> dict[str, object]:
        title = str(raw.get("title") or raw.get("headline") or raw.get("name") or "").strip()
        summary = str(raw.get("summary") or raw.get("description") or raw.get("body") or "").strip()
        event_time = ensure_datetime(raw.get("event_time") or raw.get("published_at") or raw.get("publishedAt") or raw.get("timestamp")) or utc_now()
        entities = [str(item) for item in raw.get("entities", []) if str(item).strip()]
        if not entities:
            entities = self._infer_entities(f"{title} {summary}")
        event_id = str(raw.get("event_id") or raw.get("id") or self._build_event_id(source, title, event_time))
        return {
            "event_id": event_id,
            "source": str(raw.get("source") or source),
            "title": title,
            "summary": summary,
            "category": str(raw.get("category") or default_type),
            "event_type": str(raw.get("event_type") or default_type),
            "event_time": event_time,
            "detection_time": ensure_datetime(raw.get("detection_time") or raw.get("detected_at")) or event_time,
            "entities": entities,
            "importance_score": safe_float(raw.get("importance_score") or raw.get("importance"), self._importance_from_text(title, summary)) or 0.5,
            "sentiment_score": safe_float(raw.get("sentiment_score") or raw.get("sentiment")),
            "relevance_score": safe_float(raw.get("relevance_score") or raw.get("relevance"), self._relevance_from_entities(entities)) or 0.5,
            "metadata": {
                "provider_mode": "real",
                "link": raw.get("link") or raw.get("url"),
                "provenance": source,
            },
        }

    def _build_event_id(self, source: str, title: str, event_time: datetime) -> str:
        digest = hashlib.sha1(f"{source}|{title}|{event_time.isoformat()}".encode("utf-8")).hexdigest()
        return f"evt_{digest[:16]}"

    def _importance_from_text(self, title: str, summary: str) -> float:
        text = f"{title} {summary}".lower()
        score = 0.45
        if any(keyword in text for keyword in ("fed", "inflation", "cpi", "rates", "etf", "approval", "election")):
            score += 0.25
        if any(keyword in text for keyword in ("breaking", "urgent", "surge", "plunge")):
            score += 0.1
        return min(score, 0.95)

    def _relevance_from_entities(self, entities: list[str]) -> float:
        if not entities:
            return 0.4
        if len(entities) >= 3:
            return 0.8
        return min(0.55 + len(entities) * 0.1, 0.8)

    def _infer_entities(self, text: str) -> list[str]:
        lowered = text.lower()
        entities: list[str] = []
        if "btc" in lowered or "bitcoin" in lowered:
            entities.append("BTCUSDT")
        if "eth" in lowered or "ethereum" in lowered:
            entities.append("ETHUSDT")
        if "etf" in lowered:
            entities.append("pm_crypto_etf_approval")
        if "rate" in lowered or "fed" in lowered or "inflation" in lowered:
            entities.append("pm_rate_cut_yes")
        return list(dict.fromkeys(entities))


class FallbackEventProvider:
    def __init__(self, *, real: RealEventProvider, mock: object, allow_mock_fallback: bool) -> None:
        self._adapter = FallbackProviderAdapter(
            real=real,
            mock=mock,
            allow_mock_fallback=allow_mock_fallback,
            empty_fallback_methods={
                "list_events",
                "get_event",
                "search_news",
                "fetch_recent_headlines",
                "fetch_sentiment_signals",
                "fetch_macro_calendar",
            },
        )

    async def list_events(self) -> list[dict[str, object]]:
        return await self._adapter.call("list_events")

    async def get_event(self, event_id: str) -> dict[str, object] | None:
        return await self._adapter.call("get_event", event_id)

    async def search_news(self, query: str) -> list[dict[str, object]]:
        return await self._adapter.call("search_news", query)

    async def fetch_recent_headlines(self) -> list[dict[str, object]]:
        return await self._adapter.call("fetch_recent_headlines")

    async def fetch_sentiment_signals(self) -> list[dict[str, object]]:
        return await self._adapter.call("fetch_sentiment_signals")

    async def fetch_macro_calendar(self) -> list[dict[str, object]]:
        return await self._adapter.call("fetch_macro_calendar")

    async def health_check(self) -> dict[str, object]:
        return await self._adapter.health_check()


def build_event_provider(
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    mock_provider: object | None = None,
):
    resolved = settings or get_settings()
    mock = mock_provider or MockEventProvider()
    mode = resolved.event_provider_mode
    if mode == "mock":
        return mock
    real = RealEventProvider(settings=resolved, client=client)
    if mode == "real":
        return real
    return FallbackEventProvider(
        real=real,
        mock=mock,
        allow_mock_fallback=local_fallback_allowed(resolved),
    )

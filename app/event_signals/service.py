from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.alpha_fusion.types import AlphaSourceReading
from app.config.settings import Settings, get_settings
from app.event_signals.providers import (
    MockEventProvider as BaseMockEventProvider,
    RealEventProvider as BaseRealEventProvider,
    build_event_provider,
)
from app.event_signals.types import EventSignalCandidate, NormalizedEvent
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.event_signals_repo import EventSignalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.provider_health.service import ProviderHealthService
from app.provider_health.types import ProviderIngestRun


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventProvider(Protocol):
    async def list_events(self) -> list[dict[str, object]]: ...
    async def get_event(self, event_id: str) -> dict[str, object] | None: ...
    async def search_news(self, query: str) -> list[dict[str, object]]: ...
    async def fetch_recent_headlines(self) -> list[dict[str, object]]: ...
    async def fetch_sentiment_signals(self) -> list[dict[str, object]]: ...
    async def fetch_macro_calendar(self) -> list[dict[str, object]]: ...
    async def health_check(self) -> dict[str, object]: ...


class MockEventProvider(BaseMockEventProvider):
    pass


class RealEventProvider(BaseRealEventProvider):
    pass


class EventSignalsService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        provider: EventProvider | None = None,
        repo: EventSignalsRepository | None = None,
        source_repo: AlphaSourcesRepository | None = None,
        events_repo: EventsRepository | None = None,
        provider_health_service: ProviderHealthService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or build_event_provider(
            settings=self.settings,
            mock_provider=MockEventProvider(),
        )
        self.repo = repo
        self.source_repo = source_repo
        self.events_repo = events_repo
        self.provider_health_service = provider_health_service
        self._events: OrderedDict[str, NormalizedEvent] = OrderedDict()
        self._signals: OrderedDict[str, EventSignalCandidate] = OrderedDict()

    async def refresh(self) -> None:
        requested_at = utc_now()
        raw_events: list[dict[str, object]] = []
        status = "completed"
        notes: list[str] = []
        try:
            raw_events = await self.provider.list_events()
            for raw in raw_events:
                event = self._normalize_event(raw)
                if self._is_duplicate_event(event):
                    continue
                self._events[event.event_id] = event
                if self.repo is not None:
                    self.repo.upsert_event(event)
                for signal in self._build_signals(event):
                    self._store_signal(signal)
        except Exception as exc:
            status = "failed"
            notes.append(str(exc))
            raise
        finally:
            if self.provider_health_service is not None:
                await self.provider_health_service.evaluate_provider("event_signals", self.provider)
                self.provider_health_service.record_ingest_run(
                    ProviderIngestRun(
                        run_id=self._build_id("event_signals_refresh", "ingest", requested_at),
                        provider_name="event_signals",
                        dataset_type="events",
                        requested_at=requested_at,
                        completed_at=utc_now(),
                        status=status,
                        records_requested=len(raw_events),
                        records_written=len(self._events),
                        error_summary="; ".join(notes) if notes else None,
                        notes=notes,
                        metadata={"provider_mode": getattr(self.settings, "event_provider_mode", "mock")},
                    )
                )

    async def list_events(self) -> list[NormalizedEvent]:
        if not self._events:
            await self.refresh()
        return list(self._events.values()) if self._events else (self.repo.list_events() if self.repo is not None else [])

    async def get_event(self, event_id: str) -> NormalizedEvent | None:
        if event_id in self._events:
            return self._events[event_id]
        raw = await self.provider.get_event(event_id)
        if raw is not None:
            event = self._normalize_event(raw)
            self._events[event.event_id] = event
            if self.repo is not None:
                self.repo.upsert_event(event)
            return event
        return self.repo.get_event(event_id) if self.repo is not None else None

    def list_signals(self, *, limit: int = 100) -> list[EventSignalCandidate]:
        if self.repo is not None:
            return self.repo.list_signals(limit=limit)
        return list(self._signals.values())[:limit]

    async def as_source_readings(self) -> list[AlphaSourceReading]:
        if not self._signals:
            await self.refresh()
        return [
            AlphaSourceReading(
                reading_id=f"src_{signal.signal_id}",
                source_name="event_signals",
                symbol_or_market=signal.symbol_or_market,
                direction=signal.direction,
                confidence=signal.confidence,
                expected_holding_period=signal.expected_holding_period,
                strategy_family="event_signals",
                raw_signal=signal.raw_signal,
                metadata=signal.metadata,
                timestamp=signal.timestamp,
            )
            for signal in self.list_signals(limit=100)
        ]

    async def get_provider_health(self) -> dict[str, object]:
        return await self.provider.health_check()

    def _normalize_event(self, raw: dict[str, object]) -> NormalizedEvent:
        event_time = raw.get("event_time", utc_now())
        detection_time = raw.get("detection_time") or raw.get("detected_at") or event_time
        return NormalizedEvent(
            event_id=str(raw.get("event_id")),
            source=str(raw.get("source", self.settings.event_provider_mode)),
            title=str(raw.get("title", "")),
            summary=str(raw.get("summary", "")),
            category=str(raw.get("category", "general")),
            event_type=str(raw.get("event_type", "headline")),
            event_time=event_time,
            detection_time=detection_time,
            entities=[str(item) for item in raw.get("entities", [])],
            importance_score=float(raw.get("importance_score", 0.5)),
            sentiment_score=float(raw["sentiment_score"]) if raw.get("sentiment_score") is not None else None,
            relevance_score=float(raw.get("relevance_score", 0.5)),
            event_window_state=self.classify_event_window(event_time),
            metadata=dict(raw.get("metadata", {})) if isinstance(raw.get("metadata"), dict) else {},
        )

    def classify_event_window(self, event_time: datetime) -> str:
        now = utc_now()
        age_minutes = (now - event_time).total_seconds() / 60.0
        if age_minutes < -10:
            return "pre_event"
        if -10 <= age_minutes <= 30:
            return "during_event"
        if 30 < age_minutes <= 240:
            return "post_event"
        return "stale_event"

    def decay(self, event: NormalizedEvent) -> float:
        age_minutes = max((utc_now() - event.detection_time).total_seconds() / 60.0, 0.0)
        half_life = max(self.settings.event_decay_half_life_minutes, 1)
        return 0.5 ** (age_minutes / half_life)

    def _build_signals(self, event: NormalizedEvent) -> list[EventSignalCandidate]:
        if (
            event.importance_score < self.settings.event_min_importance_score
            or event.relevance_score < self.settings.event_min_relevance_score
            or event.event_window_state == "stale_event"
        ):
            return []
        decay = self.decay(event)
        signals: list[EventSignalCandidate] = []
        for entity in event.entities:
            direction = "neutral"
            if (event.sentiment_score or 0.0) > 0.15:
                direction = "long"
            elif (event.sentiment_score or 0.0) < -0.15:
                direction = "short"
            confidence = min(1.0, event.importance_score * 0.45 + event.relevance_score * 0.3 + decay * 0.25)
            signal = EventSignalCandidate(
                signal_id=self._build_id(event.event_id, entity, event.detection_time),
                event_id=event.event_id,
                symbol_or_market=entity,
                timestamp=event.detection_time,
                direction=direction,
                confidence=round(confidence, 6),
                importance=event.importance_score,
                timeliness_decay=round(decay, 6),
                expected_holding_period="event_window",
                raw_signal={
                    "event_window_state": event.event_window_state,
                    "event_type": event.event_type,
                    "sentiment_score": event.sentiment_score,
                },
                explanation=[
                    f"importance={round(event.importance_score, 4)}",
                    f"relevance={round(event.relevance_score, 4)}",
                    f"decay={round(decay, 4)}",
                ],
                metadata={"category": event.category, "source": event.source},
            )
            signals.append(signal)
        return signals

    def _is_duplicate_event(self, event: NormalizedEvent) -> bool:
        dedupe_window = timedelta(minutes=max(self.settings.event_dedupe_window_minutes, 1))
        for existing in self._events.values():
            if existing.title.strip().lower() != event.title.strip().lower():
                continue
            if existing.source != event.source:
                continue
            if abs((existing.detection_time - event.detection_time).total_seconds()) <= dedupe_window.total_seconds():
                return True
        return False

    def _store_signal(self, signal: EventSignalCandidate) -> None:
        self._signals[signal.signal_id] = signal
        self._signals.move_to_end(signal.signal_id, last=False)
        if self.repo is not None:
            self.repo.upsert_signal(signal)
        if self.source_repo is not None:
            self.source_repo.upsert_reading(
                AlphaSourceReading(
                    reading_id=f"src_{signal.signal_id}",
                    source_name="event_signals",
                    symbol_or_market=signal.symbol_or_market,
                    direction=signal.direction,
                    confidence=signal.confidence,
                    expected_holding_period=signal.expected_holding_period,
                    strategy_family="event_signals",
                    raw_signal=signal.raw_signal,
                    metadata=signal.metadata,
                    timestamp=signal.timestamp,
                )
            )
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="event_signal_generated",
                entity_id=signal.signal_id,
                symbol=signal.symbol_or_market if len(signal.symbol_or_market) <= 32 else None,
                payload={"event_id": signal.event_id, "direction": signal.direction},
            )

    def _build_id(self, event_id: str, entity: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{event_id}|{entity}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"evt_{digest[:12]}"

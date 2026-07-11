from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.alpha_fusion.types import AlphaSourceReading
from app.config.settings import Settings, get_settings
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.mirofish_repo import MiroFishRepository
from app.simulation.types import MiroFishScenarioSummary


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MiroFishAdapter:
    """Optional advisory simulation boundary. It can never originate execution."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repo: MiroFishRepository | None = None,
        source_repo: AlphaSourcesRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repo = repo
        self.source_repo = source_repo
        self.events_repo = events_repo
        self._latest: MiroFishScenarioSummary | None = None
        self._error_count = 0
        self._last_failure_at: datetime | None = None

    def run(self, *, symbol_or_market: str, payload: dict[str, object]) -> MiroFishScenarioSummary:
        if not self.settings.enable_mirofish:
            return self._disabled_summary(symbol_or_market)
        if self.settings.mirofish_provider in {"real", "external"}:
            latest = self.latest()
            if latest is not None and latest.symbol_or_market == symbol_or_market and self._is_fresh(latest.timestamp):
                return latest
            return self._unavailable_external_summary(symbol_or_market)

        trend = _bounded_float(payload.get("trend_score"), minimum=-1.0, maximum=1.0)
        event_bias = _bounded_float(payload.get("event_bias"), minimum=-1.0, maximum=1.0)
        wallet_bias = _bounded_float(payload.get("wallet_bias"), minimum=-1.0, maximum=1.0)
        polymarket_bias = _bounded_float(payload.get("polymarket_bias"), minimum=-1.0, maximum=1.0)
        crowd_bias = max(-1.0, min(1.0, (event_bias + wallet_bias + polymarket_bias) / 3.0))
        vol_shift = abs(event_bias) * 0.4 + abs(polymarket_bias) * 0.3 + abs(trend) * 0.1
        confidence = min(0.25, 0.1 + abs(crowd_bias) * 0.1 + abs(vol_shift) * 0.15)
        direction = "long" if crowd_bias > 0.1 else "short" if crowd_bias < -0.1 else "neutral"
        summary = MiroFishScenarioSummary(
            run_id=self._build_id(symbol_or_market),
            scenario_name="mock_advisory_scenario",
            symbol_or_market=symbol_or_market,
            expected_volatility_shift=round(vol_shift, 6),
            expected_crowd_bias=round(crowd_bias, 6),
            scenario_confidence=round(confidence, 6),
            timestamp=utc_now(),
            direction_bias=direction,
            explanation="Local deterministic mock; not an independent MiroFish simulation.",
            advisory_only=True,
            provider_status="mock",
            metadata={
                "provider": "mock",
                "source_is_mock": True,
                "advisory_only": True,
                "independent_signal": False,
            },
        )
        self._store(summary)
        return summary

    def ingest_external(self, payload: dict[str, object]) -> MiroFishScenarioSummary:
        if not self.settings.enable_mirofish:
            raise ValueError("mirofish_disabled")
        timestamp = payload.get("simulation_timestamp")
        if not isinstance(timestamp, datetime):
            raise ValueError("simulation_timestamp_required")
        timestamp = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
        age_seconds = (utc_now() - timestamp).total_seconds()
        if age_seconds > self.settings.mirofish_max_data_age_seconds:
            self._record_failure()
            raise ValueError("mirofish_scenario_stale")
        if age_seconds < -self.settings.mirofish_max_future_clock_skew_seconds:
            self._record_failure()
            raise ValueError("mirofish_scenario_timestamp_in_future")

        direction = str(payload.get("direction_bias") or "neutral").lower()
        if direction not in {"long", "short", "neutral"}:
            raise ValueError("invalid_direction_bias")
        raw_confidence = _bounded_float(payload.get("scenario_confidence"), minimum=0.0, maximum=1.0)
        confidence = min(raw_confidence, self.settings.mirofish_max_scenario_confidence)
        scenario_id = str(payload.get("scenario_id") or "").strip()
        symbol_or_market = str(payload.get("symbol_or_market") or "").strip()
        if not scenario_id or not symbol_or_market:
            raise ValueError("scenario_id_and_symbol_required")
        metadata = dict(payload.get("metadata") or {})
        metadata.update(
            {
                "provider": "external_mirofish",
                "source_is_mock": False,
                "advisory_only": True,
                "independent_signal": False,
                "source_run_id": payload.get("source_run_id"),
                "scenario_id": scenario_id,
                "reported_confidence": raw_confidence,
                "confidence_capped": confidence < raw_confidence,
            }
        )
        summary = MiroFishScenarioSummary(
            run_id=self._build_external_id(scenario_id, timestamp),
            scenario_name="external_mirofish_advisory",
            symbol_or_market=symbol_or_market,
            expected_volatility_shift=_bounded_float(
                payload.get("expected_volatility_shift"),
                minimum=0.0,
                maximum=10.0,
            ),
            expected_crowd_bias=_bounded_float(
                payload.get("expected_crowd_bias"),
                minimum=-1.0,
                maximum=1.0,
            ),
            scenario_confidence=confidence,
            timestamp=timestamp,
            direction_bias=direction,
            explanation=str(payload.get("explanation") or ""),
            advisory_only=True,
            provider_status="healthy",
            metadata=metadata,
        )
        self._store(summary)
        return summary

    def latest(self) -> MiroFishScenarioSummary | None:
        if self._latest is not None:
            return self._latest
        if self.repo is not None:
            self._latest = self.repo.get_latest()
        return self._latest

    def as_source_reading(self, summary: MiroFishScenarioSummary) -> AlphaSourceReading:
        confidence = min(summary.scenario_confidence, self.settings.mirofish_max_scenario_confidence)
        return AlphaSourceReading(
            reading_id=f"src_{summary.run_id}",
            source_name="mirofish_simulation",
            symbol_or_market=summary.symbol_or_market,
            direction=summary.direction_bias,
            confidence=confidence,
            expected_holding_period="scenario_window",
            strategy_family="mirofish_simulation",
            raw_signal={
                "direction_bias": summary.direction_bias,
                "volatility_shift_estimate": summary.expected_volatility_shift,
                "advisory_only": True,
            },
            metadata={"advisory_only": True, **summary.metadata},
            timestamp=summary.timestamp,
        )

    def health_check(self) -> dict[str, object]:
        latest = self.latest()
        if not self.settings.enable_mirofish:
            return {
                "status": "degraded",
                "success_rate": 0.0,
                "stale_data_flag": True,
                "error_count": self._error_count,
                "last_failure_at": self._last_failure_at,
                "notes": ["mirofish_disabled"],
                "metadata": {"source_is_mock": False, "advisory_only": True},
            }
        source_is_mock = self.settings.mirofish_provider == "mock"
        stale = latest is None or not self._is_fresh(latest.timestamp)
        status = "degraded" if stale or source_is_mock else "healthy"
        return {
            "status": status,
            "success_rate": 0.0 if latest is None else 1.0,
            "stale_data_flag": stale,
            "error_count": self._error_count,
            "last_success_at": latest.timestamp if latest is not None else None,
            "last_failure_at": self._last_failure_at,
            "notes": ["mock_advisory_only"] if source_is_mock else [],
            "metadata": {
                "provider": self.settings.mirofish_provider,
                "source_is_mock": source_is_mock,
                "advisory_only": True,
            },
        }

    def _disabled_summary(self, symbol_or_market: str) -> MiroFishScenarioSummary:
        summary = MiroFishScenarioSummary(
            run_id=self._build_id(symbol_or_market),
            scenario_name="mirofish_disabled",
            symbol_or_market=symbol_or_market,
            expected_volatility_shift=0.0,
            expected_crowd_bias=0.0,
            scenario_confidence=0.0,
            timestamp=utc_now(),
            direction_bias="neutral",
            explanation="MiroFish is disabled.",
            advisory_only=True,
            provider_status="disabled",
            metadata={"status": "disabled", "advisory_only": True},
        )
        self._store(summary)
        return summary

    def _unavailable_external_summary(self, symbol_or_market: str) -> MiroFishScenarioSummary:
        return MiroFishScenarioSummary(
            run_id=self._build_id(symbol_or_market),
            scenario_name="mirofish_external_unavailable",
            symbol_or_market=symbol_or_market,
            expected_volatility_shift=0.0,
            expected_crowd_bias=0.0,
            scenario_confidence=0.0,
            timestamp=utc_now(),
            direction_bias="neutral",
            explanation="No fresh validated external MiroFish scenario is available.",
            advisory_only=True,
            provider_status="degraded",
            metadata={"status": "unavailable", "advisory_only": True, "source_is_mock": False},
        )

    def _store(self, summary: MiroFishScenarioSummary) -> None:
        self._latest = summary
        if self.repo is not None:
            self.repo.upsert_run(summary)
        if self.source_repo is not None:
            self.source_repo.upsert_reading(self.as_source_reading(summary))
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="mirofish_run_completed",
                entity_id=summary.run_id,
                payload={
                    "symbol_or_market": summary.symbol_or_market,
                    "scenario_confidence": summary.scenario_confidence,
                    "advisory_only": True,
                    "provider_status": summary.provider_status,
                },
            )

    def _is_fresh(self, timestamp: datetime) -> bool:
        return (utc_now() - timestamp).total_seconds() <= self.settings.mirofish_max_data_age_seconds

    def _record_failure(self) -> None:
        self._error_count += 1
        self._last_failure_at = utc_now()

    def _build_id(self, symbol_or_market: str) -> str:
        digest = hashlib.sha1(f"{symbol_or_market}|{utc_now().isoformat()}".encode("utf-8")).hexdigest()
        return f"mir_{digest[:12]}"

    def _build_external_id(self, scenario_id: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{scenario_id}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"mir_ext_{digest[:12]}"


def _bounded_float(value: object, *, minimum: float, maximum: float) -> float:
    try:
        resolved = float(value or 0.0)
    except (TypeError, ValueError):
        resolved = 0.0
    return max(minimum, min(maximum, resolved))

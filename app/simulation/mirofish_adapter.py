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
    """Optional advisory simulation adapter. It can inform research, never force live execution."""

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

    def run(self, *, symbol_or_market: str, payload: dict[str, object]) -> MiroFishScenarioSummary:
        if not self.settings.enable_mirofish:
            summary = MiroFishScenarioSummary(
                run_id=self._build_id(symbol_or_market),
                scenario_name="mirofish_disabled",
                symbol_or_market=symbol_or_market,
                expected_volatility_shift=0.0,
                expected_crowd_bias=0.0,
                scenario_confidence=0.0,
                timestamp=utc_now(),
                metadata={"status": "disabled"},
            )
            self._store(summary)
            return summary
        trend = float(payload.get("trend_score", 0.0))
        event_bias = float(payload.get("event_bias", 0.0))
        wallet_bias = float(payload.get("wallet_bias", 0.0))
        polymarket_bias = float(payload.get("polymarket_bias", 0.0))
        crowd_bias = max(-1.0, min(1.0, (event_bias + wallet_bias + polymarket_bias) / 3.0))
        vol_shift = abs(event_bias) * 0.4 + abs(polymarket_bias) * 0.3 + abs(trend) * 0.1
        confidence = min(1.0, 0.35 + abs(crowd_bias) * 0.25 + abs(vol_shift) * 0.4)
        summary = MiroFishScenarioSummary(
            run_id=self._build_id(symbol_or_market),
            scenario_name="advisory_scenario",
            symbol_or_market=symbol_or_market,
            expected_volatility_shift=round(vol_shift, 6),
            expected_crowd_bias=round(crowd_bias, 6),
            scenario_confidence=round(confidence, 6),
            timestamp=utc_now(),
            metadata={"provider": self.settings.mirofish_provider},
        )
        self._store(summary)
        return summary

    def latest(self) -> MiroFishScenarioSummary | None:
        if self._latest is not None:
            return self._latest
        if self.repo is not None:
            return self.repo.get_latest()
        return None

    def as_source_reading(self, summary: MiroFishScenarioSummary) -> AlphaSourceReading:
        direction = "neutral"
        if summary.expected_crowd_bias > 0.1:
            direction = "long"
        elif summary.expected_crowd_bias < -0.1:
            direction = "short"
        return AlphaSourceReading(
            reading_id=f"src_{summary.run_id}",
            source_name="mirofish_simulation",
            symbol_or_market=summary.symbol_or_market,
            direction=direction,
            confidence=summary.scenario_confidence,
            expected_holding_period="scenario_window",
            strategy_family="mirofish_simulation",
            raw_signal={
                "direction_bias": direction,
                "volatility_shift_estimate": summary.expected_volatility_shift,
            },
            metadata=summary.metadata,
            timestamp=summary.timestamp,
        )

    def health_check(self) -> dict[str, object]:
        if not self.settings.enable_mirofish:
            return {"status": "degraded", "success_rate": 0.0, "stale_data_flag": True, "error_count": 0, "notes": ["mirofish_disabled"]}
        return {"status": "healthy" if self._latest is not None else "degraded", "success_rate": 1.0 if self._latest is not None else 0.5, "stale_data_flag": False, "error_count": 0}

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
                payload={"symbol_or_market": summary.symbol_or_market, "scenario_confidence": summary.scenario_confidence},
            )

    def _build_id(self, symbol_or_market: str) -> str:
        digest = hashlib.sha1(f"{symbol_or_market}|{utc_now().isoformat()}".encode("utf-8")).hexdigest()
        return f"mir_{digest[:12]}"

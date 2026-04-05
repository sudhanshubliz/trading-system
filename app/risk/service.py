from __future__ import annotations

import hashlib
import inspect
import logging
from collections import OrderedDict
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable

from app.config.settings import Settings, get_settings
from app.core.logging import log_structured_event
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.risk_repo import RiskRepository
from app.risk.engine import RiskEngine
from app.risk.exposure import ExposureManager
from app.risk.types import AccountState, ExposureState, RiskAssessment, RiskSummary, RiskValidationInput
from app.signals.types import CandidateSignal

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RiskService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        signal_service: object | None = None,
        market_data_service: object | None = None,
        time_provider: Callable[[], datetime] | None = None,
        risk_repo: RiskRepository | None = None,
        events_repo: EventsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.signal_service = signal_service
        self.market_data_service = market_data_service
        self.time_provider = time_provider or utc_now
        self.risk_repo = risk_repo
        self.events_repo = events_repo
        self.engine = RiskEngine(self.settings, time_provider=self.time_provider)
        self.exposure_manager = ExposureManager(self.settings, time_provider=self.time_provider)
        self._assessments: OrderedDict[str, RiskAssessment] = OrderedDict()

    async def stop(self) -> None:
        return None

    def get_summary(self) -> RiskSummary:
        return self.exposure_manager.get_risk_summary(list(self._assessments.values()))

    def get_assessments(self) -> list[RiskAssessment]:
        return [replace(assessment) for assessment in self._assessments.values()]

    def get_assessment(self, assessment_id: str) -> RiskAssessment | None:
        for assessment in self._assessments.values():
            if assessment.assessment_id == assessment_id:
                return replace(assessment)
        if self.risk_repo is not None:
            assessment = self.risk_repo.get_assessment(assessment_id)
            if assessment is not None:
                self._store_assessment(assessment)
                return replace(assessment)
        return None

    async def validate_signal_payload(self, payload: Any) -> RiskAssessment:
        validation_input = self._to_validation_input(payload)
        existing = self._assessments.get(validation_input.signal_id)
        if existing is not None:
            return replace(existing)

        account_state = self.exposure_manager.get_account_state(list(self._assessments.values()))
        exposure_state = self.exposure_manager.get_exposure_state(list(self._assessments.values()))
        market_data_status = await self._get_market_data_status()

        assessment = self.engine.assess(
            validation_input,
            account_state,
            exposure_state,
            market_data_status=market_data_status,
            cycle_limit_passed=True,
        )
        self._store_assessment(assessment)
        return replace(assessment)

    async def evaluate_signals(self, symbols: list[str] | None = None) -> list[RiskAssessment]:
        signal_service = self.signal_service
        if signal_service is None:
            logger.warning("risk evaluation skipped because signal service is unavailable")
            return []

        evaluate_symbols = getattr(signal_service, "evaluate_symbols", None)
        if evaluate_symbols is None:
            logger.warning("risk evaluation skipped because signal service has no evaluate_symbols")
            return []

        candidate_signals = await self._maybe_await(evaluate_symbols(symbols))
        if not candidate_signals:
            return []

        market_data_status = await self._get_market_data_status()
        results: list[RiskAssessment] = []
        cycle_approved_count = 0

        for candidate_signal in candidate_signals:
            validation_input = self._to_validation_input(candidate_signal)
            existing = self._assessments.get(validation_input.signal_id)
            if existing is not None:
                results.append(replace(existing))
                if existing.final_decision == "approved_for_review":
                    cycle_approved_count += 1
                continue

            account_state = self.exposure_manager.get_account_state(list(self._assessments.values()))
            exposure_state = self.exposure_manager.get_exposure_state(list(self._assessments.values()))
            assessment = self.engine.assess(
                validation_input,
                account_state,
                exposure_state,
                market_data_status=market_data_status,
                cycle_limit_passed=cycle_approved_count < 3,
            )
            if assessment.final_decision == "approved_for_review":
                cycle_approved_count += 1

            self._store_assessment(assessment)
            results.append(replace(assessment))

        return results

    def _store_assessment(self, assessment: RiskAssessment) -> None:
        signal_id = assessment.signal_id
        self._assessments[signal_id] = assessment
        self._assessments.move_to_end(signal_id, last=False)
        while len(self._assessments) > self.settings.risk_store_limit:
            self._assessments.popitem(last=True)
        if self.risk_repo is not None:
            self.risk_repo.upsert_assessment(assessment)
        event_type = "risk_passed" if assessment.final_decision == "approved_for_review" else "risk_rejected"
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type=event_type,
                entity_id=assessment.assessment_id,
                symbol=assessment.symbol,
                payload={
                    "signal_id": assessment.signal_id,
                    "decision": assessment.final_decision,
                    "rejection_reasons": assessment.rejection_reasons,
                },
            )
        log_structured_event(
            logger,
            event_type,
            assessment_id=assessment.assessment_id,
            signal_id=assessment.signal_id,
            symbol=assessment.symbol,
            decision=assessment.final_decision,
            rejection_reasons=assessment.rejection_reasons,
        )

    async def _get_market_data_status(self) -> str | None:
        market_data_service = self.market_data_service
        if market_data_service is None:
            return None

        get_health = getattr(market_data_service, "get_health", None)
        if get_health is None:
            return None

        try:
            health = await self._maybe_await(get_health())
        except Exception:
            logger.warning("failed to fetch market data health for risk assessment")
            return "degraded"

        if isinstance(health, dict):
            status = health.get("status")
            return str(status) if status is not None else None

        status = getattr(health, "status", None)
        return str(status) if status is not None else None

    def _to_validation_input(self, payload: Any) -> RiskValidationInput:
        data = self._to_mapping(payload)
        signal_id = str(data.get("signal_id") or self._derive_signal_id(data))
        generated_at = data.get("generated_at")
        if not isinstance(generated_at, datetime):
            generated_at = self.time_provider()

        return RiskValidationInput(
            signal_id=signal_id,
            symbol=str(data.get("symbol", "")).upper(),
            side=str(data.get("side", "")).lower(),
            strategy_name=str(data.get("strategy_name", "")),
            confidence_score=int(data.get("confidence_score", 0)),
            entry_price=float(data.get("entry_price", 0.0)),
            stop_loss=float(data.get("stop_loss", 0.0)),
            target_1=float(data.get("target_1", 0.0)),
            target_2=float(data["target_2"]) if data.get("target_2") is not None else None,
            reward_risk_ratio=(
                float(data["reward_risk_ratio"]) if data.get("reward_risk_ratio") is not None else None
            ),
            rationale=list(data.get("rationale", [])),
            generated_at=generated_at.astimezone(timezone.utc),
        )

    def _to_mapping(self, payload: Any) -> dict[str, Any]:
        if is_dataclass(payload):
            return asdict(payload)
        if hasattr(payload, "model_dump"):
            return payload.model_dump()
        if isinstance(payload, dict):
            return payload
        raise TypeError("Unsupported payload type for risk validation")

    def _derive_signal_id(self, data: dict[str, Any]) -> str:
        seed = "|".join(
            [
                str(data.get("symbol", "")).upper(),
                str(data.get("side", "")).lower(),
                str(data.get("strategy_name", "")),
                str(data.get("entry_price", "")),
                str(data.get("stop_loss", "")),
                str(data.get("target_1", "")),
            ]
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        return f"sig_{digest[:12]}"

    async def _maybe_await(self, value: object) -> object:
        if inspect.isawaitable(value):
            return await value
        return value

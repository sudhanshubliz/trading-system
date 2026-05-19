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
from app.execution_quality.service import ExecutionQualityService
from app.risk.locks import RiskLockManager
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.risk_repo import RiskRepository
from app.risk.engine import RiskEngine
from app.risk.exposure import ExposureManager
from app.risk.types import AccountState, ExposureState, RiskAssessment, RiskCheckResult, RiskSummary, RiskValidationInput
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
        risk_lock_manager: RiskLockManager | None = None,
        execution_quality_service: ExecutionQualityService | None = None,
        arbitrage_service: object | None = None,
        microstructure_service: object | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.signal_service = signal_service
        self.market_data_service = market_data_service
        self.time_provider = time_provider or utc_now
        self.risk_repo = risk_repo
        self.events_repo = events_repo
        self.risk_lock_manager = risk_lock_manager
        self.execution_quality_service = execution_quality_service
        self.arbitrage_service = arbitrage_service
        self.microstructure_service = microstructure_service
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

    def list_current_locks(self) -> list[dict[str, object]]:
        if self.risk_lock_manager is None:
            return []
        return [
            {
                "event_id": item.event_id,
                "lock_key": item.lock_key,
                "lock_type": item.lock_type,
                "scope": item.scope,
                "scope_key": item.scope_key,
                "severity": item.severity,
                "reason": item.reason,
                "metrics_snapshot": item.metrics_snapshot,
                "is_active": item.is_active,
                "triggered_at": item.triggered_at,
                "released_at": item.released_at,
                "metadata": item.metadata,
            }
            for item in self.risk_lock_manager.list_current()
        ]

    def list_lock_history(self, *, limit: int = 100) -> list[dict[str, object]]:
        if self.risk_lock_manager is None:
            return []
        return [
            {
                "event_id": item.event_id,
                "lock_key": item.lock_key,
                "lock_type": item.lock_type,
                "scope": item.scope,
                "scope_key": item.scope_key,
                "severity": item.severity,
                "reason": item.reason,
                "metrics_snapshot": item.metrics_snapshot,
                "is_active": item.is_active,
                "triggered_at": item.triggered_at,
                "released_at": item.released_at,
                "metadata": item.metadata,
            }
            for item in self.risk_lock_manager.list_history(limit=limit)
        ]

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
        assessment = await self._apply_phase2_risk_locks(assessment, validation_input)
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
            assessment = await self._apply_phase2_risk_locks(assessment, validation_input)
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

    async def _apply_phase2_risk_locks(
        self,
        assessment: RiskAssessment,
        validation_input: RiskValidationInput,
    ) -> RiskAssessment:
        if self.risk_lock_manager is None:
            return assessment

        symbol = validation_input.symbol.upper()
        active_before = {item.lock_key for item in self.risk_lock_manager.list_current()}
        payload_locks: list[dict[str, object]] = []

        market_data_service = self.market_data_service
        if market_data_service is not None:
            get_order_book = getattr(market_data_service, "get_order_book", None)
            if get_order_book is not None:
                order_book = await self._maybe_await(get_order_book(symbol))
                if self.settings.enable_stale_data_lock:
                    stale = order_book is None or getattr(order_book, "updated_at", None) is None or (
                        (self.time_provider() - order_book.updated_at).total_seconds() > self.settings.microstructure_stale_book_seconds
                    )
                    self._toggle_lock(
                        enabled=True,
                        condition=stale,
                        lock_type="stale_data_lock",
                        scope="symbol",
                        scope_key=symbol,
                        severity="high",
                        reason="order_book_stale_or_missing",
                        metrics_snapshot={"symbol": symbol},
                    )
                if self.settings.enable_liquidity_thin_lock and order_book is not None:
                    total_depth = sum(level.price * level.quantity for level in list(getattr(order_book, "bids", []))[:2] + list(getattr(order_book, "asks", []))[:2])
                    spread = 0.0
                    bids = list(getattr(order_book, "bids", []))
                    asks = list(getattr(order_book, "asks", []))
                    if bids and asks:
                        mid = (bids[0].price + asks[0].price) / 2
                        if mid > 0:
                            spread = ((asks[0].price - bids[0].price) / mid) * 10000
                    thin = total_depth < self.settings.microstructure_min_depth_usd or spread > self.settings.microstructure_max_relative_spread_bps
                    self._toggle_lock(
                        enabled=True,
                        condition=thin,
                        lock_type="liquidity_thin_lock",
                        scope="symbol",
                        scope_key=symbol,
                        severity="high",
                        reason="insufficient_depth_or_spread_wide",
                        metrics_snapshot={"total_depth_usd": total_depth, "spread_bps": spread},
                    )

        if self.settings.enable_volatility_shock_lock and self.microstructure_service is not None:
            latest_micro = self.microstructure_service.get_latest(symbol)
            shock = latest_micro is not None and (
                latest_micro.market_state in {"toxic_flow_risk", "unstable_quotes"}
                or (latest_micro.realized_short_volatility or 0.0) >= self.settings.microstructure_vol_shock_threshold
            )
            self._toggle_lock(
                enabled=True,
                condition=shock,
                lock_type="volatility_shock_lock",
                scope="symbol",
                scope_key=symbol,
                severity="critical",
                reason="microstructure_volatility_shock",
                metrics_snapshot={
                    "market_state": latest_micro.market_state if latest_micro else None,
                    "realized_short_volatility": latest_micro.realized_short_volatility if latest_micro else None,
                },
            )

        if self.settings.enable_execution_anomaly_lock and self.execution_quality_service is not None:
            anomaly_state = self.execution_quality_service.recent_anomaly_state(limit=10)
            self._toggle_lock(
                enabled=True,
                condition=bool(anomaly_state.get("is_anomalous")),
                lock_type="execution_anomaly_lock",
                scope="system",
                scope_key="global",
                severity="critical",
                reason="recent_execution_quality_degraded",
                metrics_snapshot=anomaly_state,
            )

        if self.settings.enable_basis_data_integrity_lock and self.arbitrage_service is not None:
            integrity = await self._maybe_await(self.arbitrage_service.get_integrity_status(symbol))
            self._toggle_lock(
                enabled=True,
                condition=not bool(integrity.get("healthy")),
                lock_type="basis_data_integrity_lock",
                scope="symbol",
                scope_key=symbol,
                severity="medium",
                reason=str(integrity.get("reason", "basis_data_unhealthy")),
                metrics_snapshot=integrity,
            )

        active_current = self.risk_lock_manager.list_current()
        for item in active_current:
            if item.scope == "system" or (item.scope == "symbol" and item.scope_key == symbol):
                payload_locks.append(
                    {
                        "lock_type": item.lock_type,
                        "scope": item.scope,
                        "scope_key": item.scope_key,
                        "severity": item.severity,
                        "reason": item.reason,
                    }
                )

        if payload_locks:
            checks = list(assessment.checks)
            for lock in payload_locks:
                checks.append(
                    RiskCheckResult(
                        name=f"{lock['lock_type']}_passed",
                        passed=False,
                        details=str(lock["reason"]),
                    )
                )
            rejection_reasons = list(dict.fromkeys([*assessment.rejection_reasons, *[str(item["reason"]) for item in payload_locks]]))
            return replace(
                assessment,
                final_decision="rejected",
                failed_checks_count=assessment.failed_checks_count + len(payload_locks),
                checks=checks,
                rejection_reasons=rejection_reasons,
                active_risk_locks=payload_locks,
            )

        if active_before:
            for lock in list(self.risk_lock_manager.list_current()):
                if lock.lock_key in active_before and lock.scope == "symbol" and lock.scope_key == symbol:
                    pass
        return replace(assessment, active_risk_locks=[])

    def _toggle_lock(
        self,
        *,
        enabled: bool,
        condition: bool,
        lock_type: str,
        scope: str,
        scope_key: str,
        severity: str,
        reason: str,
        metrics_snapshot: dict[str, object],
    ) -> None:
        if not enabled or self.risk_lock_manager is None:
            return
        if condition:
            self.risk_lock_manager.activate(
                lock_type=lock_type,
                scope=scope,
                scope_key=scope_key,
                severity=severity,
                reason=reason,
                metrics_snapshot=metrics_snapshot,
            )
        else:
            self.risk_lock_manager.clear(lock_type=lock_type, scope=scope, scope_key=scope_key, reason="condition_cleared")

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
            metadata=dict(data.get("metadata", {})),
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

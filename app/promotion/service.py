from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone

from app.config.settings import Settings, get_settings
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.promotion_repo import PromotionRepository
from app.promotion.types import PromotionReview, StrategyPromotionStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


STAGE_ORDER = ["research", "paper", "shadow", "guarded_live", "scaled_live"]


class PromotionService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        execution_quality_service: object | None = None,
        trades_repo: object | None = None,
        provider_health_service: object | None = None,
        events_repo: EventsRepository | None = None,
        repo: PromotionRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.execution_quality_service = execution_quality_service
        self.trades_repo = trades_repo
        self.provider_health_service = provider_health_service
        self.events_repo = events_repo
        self.repo = repo
        self._status: dict[str, StrategyPromotionStatus] = {}

    def list_status(self) -> list[StrategyPromotionStatus]:
        if self._status:
            return list(self._status.values())
        if self.repo is not None:
            return self.repo.list_status()
        return []

    def get_status(self, strategy_name: str) -> StrategyPromotionStatus | None:
        if strategy_name in self._status:
            return self._status[strategy_name]
        if self.repo is not None:
            return self.repo.get_status(strategy_name)
        return None

    def evaluate_strategy_for_promotion(self, strategy_name: str) -> StrategyPromotionStatus:
        records = self.execution_quality_service.list_records(strategy_name=strategy_name, limit=500) if self.execution_quality_service is not None else []
        sample_count = len(records)
        quality_avg = round(sum(item.fill_quality_score for item in records) / sample_count, 6) if sample_count else 0.0
        expectancy = 0.0
        drawdown = 0.0
        if self.trades_repo is not None and hasattr(self.trades_repo, "list_trades"):
            trades = self.trades_repo.list_trades("paper")
            strategy_trades = [trade for trade in trades if trade.strategy_name == strategy_name]
            sample_count = max(sample_count, len(strategy_trades))
            if strategy_trades:
                pnls = [float(getattr(trade, "realized_pnl", 0.0)) for trade in strategy_trades]
                expectancy = round(sum(pnls) / len(pnls), 6)
                cumulative = 0.0
                peak = 0.0
                dd = 0.0
                for pnl in pnls:
                    cumulative += pnl
                    peak = max(peak, cumulative)
                    dd = min(dd, cumulative - peak)
                drawdown = abs(round(dd, 6))
        provider_summary = self.provider_health_service.build_summary() if self.provider_health_service is not None else {"count": 0, "healthy": 0}
        provider_health_score = round((provider_summary.get("healthy", 0) / max(provider_summary.get("count", 1), 1)), 6)
        incident_count = len([event for event in self.events_repo.list_critical_events(limit=500) if strategy_name in str(event)]) if self.events_repo is not None else 0
        unresolved_incidents = 0
        if hasattr(self, "openclaw_bridge") and self.openclaw_bridge is not None and hasattr(self.openclaw_bridge, "list_incidents"):
            unresolved_incidents = len(
                [
                    item
                    for item in self.openclaw_bridge.list_incidents(limit=500)
                    if item.get("status") != "resolved" and strategy_name in str(item.get("related_strategy") or item.get("title") or "")
                ]
            )
        backfill_failures = 0
        if hasattr(self, "research_service") and self.research_service is not None and hasattr(self.research_service, "summarize_backfill_status"):
            backfill_failures = int(self.research_service.summarize_backfill_status().get("failed", 0))
        current_stage = self.get_status(strategy_name).current_stage if self.get_status(strategy_name) is not None else "research"
        explanation = [
            f"sample_count={sample_count}",
            f"expectancy={expectancy}",
            f"drawdown={drawdown}",
            f"execution_quality_avg={quality_avg}",
            f"provider_health_score={provider_health_score}",
            f"incident_count={incident_count}",
            f"unresolved_incidents={unresolved_incidents}",
            f"backfill_failures={backfill_failures}",
        ]
        eligible = (
            sample_count >= self.settings.promotion_min_sample_count
            and expectancy >= self.settings.promotion_min_expectancy
            and drawdown <= self.settings.promotion_max_drawdown
            and quality_avg >= self.settings.promotion_min_execution_quality
            and provider_health_score >= self.settings.promotion_min_provider_health
            and incident_count == 0
            and unresolved_incidents == 0
            and backfill_failures == 0
        )
        status = StrategyPromotionStatus(
            strategy_name=strategy_name,
            current_stage=current_stage,
            sample_count=sample_count,
            net_expectancy_after_costs=expectancy,
            drawdown=drawdown,
            execution_quality_avg=quality_avg,
            provider_health_score=provider_health_score,
            incident_count=incident_count,
            last_review_at=utc_now(),
            eligible_for_promotion=eligible,
            promotion_explanation=explanation,
        )
        self._status[strategy_name] = status
        if self.repo is not None:
            self.repo.upsert_status(status)
        return status

    def recommend_stage_change(self, strategy_name: str) -> dict[str, object]:
        status = self.evaluate_strategy_for_promotion(strategy_name)
        current_index = STAGE_ORDER.index(status.current_stage) if status.current_stage in STAGE_ORDER else 0
        next_stage = STAGE_ORDER[min(current_index + 1, len(STAGE_ORDER) - 1)] if status.eligible_for_promotion else status.current_stage
        return {
            "strategy_name": strategy_name,
            "current_stage": status.current_stage,
            "recommended_stage": next_stage,
            "eligible": status.eligible_for_promotion,
            "explanation": status.promotion_explanation,
        }

    def record_review(self, strategy_name: str) -> PromotionReview:
        recommendation = self.recommend_stage_change(strategy_name)
        review = PromotionReview(
            review_id=self._build_id(strategy_name),
            strategy_name=strategy_name,
            stage_name=str(recommendation["recommended_stage"]),
            decision="promote" if recommendation["eligible"] and recommendation["recommended_stage"] != recommendation["current_stage"] else "hold",
            reviewed_at=utc_now(),
            explanation=list(recommendation["explanation"]),
            metadata={"current_stage": recommendation["current_stage"]},
        )
        if review.decision == "promote":
            existing = self._status.get(strategy_name)
            if existing is not None:
                self._status[strategy_name] = replace(existing, current_stage=review.stage_name, last_review_at=review.reviewed_at)
                if self.repo is not None:
                    self.repo.upsert_status(self._status[strategy_name])
        if self.repo is not None:
            self.repo.append_review(review)
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="promotion_review_recorded",
                entity_id=review.review_id,
                payload={"strategy_name": strategy_name, "decision": review.decision, "stage_name": review.stage_name},
            )
        return review

    def list_reviews(self, *, limit: int = 100) -> list[PromotionReview]:
        if self.repo is not None:
            return self.repo.list_reviews(limit=limit)
        return []

    def get_blockers(self, strategy_name: str) -> dict[str, object]:
        status = self.evaluate_strategy_for_promotion(strategy_name)
        blockers: list[str] = []
        if status.sample_count < self.settings.promotion_min_sample_count:
            blockers.append("insufficient_sample_size")
        if status.net_expectancy_after_costs < self.settings.promotion_min_expectancy:
            blockers.append("expectancy_below_threshold")
        if status.drawdown > self.settings.promotion_max_drawdown:
            blockers.append("drawdown_above_threshold")
        if status.execution_quality_avg < self.settings.promotion_min_execution_quality:
            blockers.append("execution_quality_below_threshold")
        if status.provider_health_score < self.settings.promotion_min_provider_health:
            blockers.append("provider_health_below_threshold")
        if status.incident_count > 0:
            blockers.append("critical_incidents_present")
        return {
            "strategy_name": strategy_name,
            "current_stage": status.current_stage,
            "eligible": status.eligible_for_promotion,
            "blockers": blockers,
            "explanation": status.promotion_explanation,
        }

    def get_evidence(self, strategy_name: str) -> dict[str, object]:
        status = self.evaluate_strategy_for_promotion(strategy_name)
        quality_records = self.execution_quality_service.list_records(strategy_name=strategy_name, limit=50) if self.execution_quality_service is not None else []
        strategy_trades = []
        if self.trades_repo is not None and hasattr(self.trades_repo, "list_trades"):
            strategy_trades = [trade for trade in self.trades_repo.list_trades("paper") if trade.strategy_name == strategy_name][:50]
        latest_review = next((item for item in self.list_reviews(limit=100) if item.strategy_name == strategy_name), None)
        return {
            "strategy_name": strategy_name,
            "status": status,
            "recent_execution_quality": quality_records,
            "recent_trades": strategy_trades,
            "latest_review": latest_review,
            "recommendation": self.recommend_stage_change(strategy_name),
        }

    def _build_id(self, strategy_name: str) -> str:
        digest = hashlib.sha1(f"{strategy_name}|{utc_now().isoformat()}".encode("utf-8")).hexdigest()
        return f"prv_{digest[:12]}"

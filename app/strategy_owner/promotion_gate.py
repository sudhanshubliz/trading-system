from __future__ import annotations

from app.promotion.service import PromotionService


def gate_strategy(
    promotion_service: PromotionService | None,
    *,
    strategy_name: str | None,
) -> tuple[bool, list[str]]:
    if promotion_service is None or not strategy_name:
        return True, []
    status = promotion_service.get_status(strategy_name)
    if status is None:
        return True, []
    reasons: list[str] = []
    if status.current_stage == "research":
        reasons.append("strategy_stage_research_only")
    if status.incident_count > 0:
        reasons.append("strategy_incident_blocker")
    if status.provider_health_score < promotion_service.settings.promotion_min_provider_health:
        reasons.append("strategy_provider_health_below_floor")
    return len(reasons) == 0, reasons

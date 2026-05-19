from __future__ import annotations

from app.execution_quality.service import ExecutionQualityService
from app.promotion.service import PromotionService


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def normalize_expected_value_bps(edge_bps: float, *, floor: float = 0.0, ceiling: float = 50.0) -> float:
    if ceiling <= floor:
        return 0.0
    bounded = max(floor, min(edge_bps, ceiling))
    return clamp((bounded - floor) / (ceiling - floor))


def execution_quality_score(
    service: ExecutionQualityService | None,
    *,
    strategy_name: str | None,
) -> float:
    if service is None or not strategy_name:
        return 0.55
    records = service.list_records(strategy_name=strategy_name, limit=50)
    if not records:
        return 0.55
    return clamp(sum(item.fill_quality_score for item in records) / len(records))


def historical_performance_score(
    service: PromotionService | None,
    *,
    strategy_name: str | None,
) -> float:
    if service is None or not strategy_name:
        return 0.55
    status = service.get_status(strategy_name)
    if status is None:
        return 0.55
    sample_component = clamp(status.sample_count / max(service.settings.promotion_min_sample_count, 1))
    expectancy_component = 1.0 if status.net_expectancy_after_costs >= service.settings.promotion_min_expectancy else 0.25
    drawdown_component = 1.0 if status.drawdown <= service.settings.promotion_max_drawdown_pct else 0.2
    quality_component = clamp(status.execution_quality_avg)
    provider_component = clamp(status.provider_health_score)
    return clamp(
        (sample_component * 0.15)
        + (expectancy_component * 0.25)
        + (drawdown_component * 0.20)
        + (quality_component * 0.20)
        + (provider_component * 0.20)
    )

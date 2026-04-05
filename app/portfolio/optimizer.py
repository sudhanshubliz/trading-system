from __future__ import annotations

from app.config.settings import Settings
from app.persistence.db import safe_float
from app.portfolio.types import PortfolioState
from app.risk.types import RiskAssessment


def candidate_score(
    assessment: RiskAssessment,
    state: PortfolioState,
    *,
    settings: Settings,
    recent_strategy_performance: dict[str, float] | None = None,
) -> float:
    strategy_performance = recent_strategy_performance or {}
    reward_risk = safe_float(assessment.actual_reward_risk_ratio or assessment.min_reward_risk_ratio)
    confidence = safe_float(assessment.risk_score)
    strategy_allocation = state.strategy_allocations.get(assessment.strategy_name)
    symbol_allocation = state.symbol_allocations.get(assessment.symbol)
    diversification_bonus = 0.0
    if strategy_allocation is None:
        diversification_bonus += 4.0
    if symbol_allocation is None:
        diversification_bonus += 6.0
    if state.open_positions_by_symbol.get(assessment.symbol, 0) == 0:
        diversification_bonus += 2.0

    strategy_penalty = safe_float(strategy_allocation.allocation_pct if strategy_allocation else 0.0) * 0.15
    symbol_penalty = safe_float(symbol_allocation.allocation_pct if symbol_allocation else 0.0) * 0.2
    performance_bonus = safe_float(strategy_performance.get(assessment.strategy_name, 0.0))
    ranking_mode_bonus = 5.0 if settings.portfolio_ranking_mode == "score" else 0.0
    return safe_float(
        confidence
        + reward_risk * 18.0
        + diversification_bonus
        + performance_bonus
        + ranking_mode_bonus
        - strategy_penalty
        - symbol_penalty
    )


def rank_candidates(
    settings: Settings,
    assessments: list[RiskAssessment],
    state: PortfolioState,
    *,
    recent_strategy_performance: dict[str, float] | None = None,
) -> list[tuple[RiskAssessment, float]]:
    ranked = [
        (
            assessment,
            candidate_score(
                assessment,
                state,
                settings=settings,
                recent_strategy_performance=recent_strategy_performance,
            ),
        )
        for assessment in assessments
    ]
    ranked.sort(
        key=lambda item: (
            -safe_float(item[1]),
            -safe_float(item[0].actual_reward_risk_ratio or 0.0),
            -safe_float(item[0].risk_score),
            item[0].symbol,
            item[0].strategy_name,
            item[0].assessment_id,
        )
    )
    return ranked

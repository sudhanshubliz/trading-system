from __future__ import annotations

from collections import defaultdict

from app.config.settings import Settings
from app.portfolio.allocator import PortfolioAllocator
from app.portfolio.optimizer import rank_candidates as rank_candidate_batch
from app.portfolio.types import PortfolioDecision, PortfolioState
from app.risk.types import RiskAssessment


class PortfolioOrchestrator:
    def __init__(self, settings: Settings, allocator: PortfolioAllocator) -> None:
        self.settings = settings
        self.allocator = allocator

    def rank_candidates(
        self,
        assessments: list[RiskAssessment],
        state: PortfolioState,
        *,
        recent_strategy_performance: dict[str, float] | None = None,
    ) -> list[tuple[RiskAssessment, float]]:
        return rank_candidate_batch(
            self.settings,
            assessments,
            state,
            recent_strategy_performance=recent_strategy_performance,
        )

    def detect_conflicts(
        self,
        ranked_candidates: list[tuple[RiskAssessment, float]],
        state: PortfolioState,
    ) -> dict[str, list[str]]:
        conflicts: dict[str, list[str]] = defaultdict(list)
        chosen_side_by_symbol: dict[str, str] = {}
        chosen_strategy_by_symbol: dict[str, set[str]] = defaultdict(set)
        for assessment, _score in ranked_candidates:
            normalized_side = assessment.side.lower()
            if any(
                existing.lower() != normalized_side
                for existing in state.position_sides_by_symbol.get(assessment.symbol, [])
            ):
                conflicts[assessment.assessment_id].append("conflicting_symbol_side")
                continue
            existing_choice = chosen_side_by_symbol.get(assessment.symbol)
            if existing_choice is not None and existing_choice != normalized_side:
                conflicts[assessment.assessment_id].append("conflicting_symbol_side")
                continue
            if assessment.strategy_name in chosen_strategy_by_symbol[assessment.symbol]:
                conflicts[assessment.assessment_id].append("duplicate_symbol_strategy_candidate")
                continue
            chosen_side_by_symbol[assessment.symbol] = normalized_side
            chosen_strategy_by_symbol[assessment.symbol].add(assessment.strategy_name)
        return dict(conflicts)

    def apply_constraints(
        self,
        ranked_candidates: list[tuple[RiskAssessment, float]],
        state: PortfolioState,
        *,
        execution_mode: str,
        rollout_capital_limit: float | None = None,
        recent_strategy_performance: dict[str, float] | None = None,
    ) -> list[PortfolioDecision]:
        del recent_strategy_performance
        conflict_map = self.detect_conflicts(ranked_candidates, state)
        return self.allocator.allocate_batch(
            ranked_candidates,
            state,
            execution_mode=execution_mode,
            rollout_capital_limit=rollout_capital_limit,
            conflict_map=conflict_map,
        )

    def select_candidates_for_execution(
        self,
        assessments: list[RiskAssessment],
        state: PortfolioState,
        *,
        execution_mode: str,
        rollout_capital_limit: float | None = None,
        recent_strategy_performance: dict[str, float] | None = None,
    ) -> list[PortfolioDecision]:
        ranked = self.rank_candidates(
            assessments,
            state,
            recent_strategy_performance=recent_strategy_performance,
        )
        return self.apply_constraints(
            ranked,
            state,
            execution_mode=execution_mode,
            rollout_capital_limit=rollout_capital_limit,
        )

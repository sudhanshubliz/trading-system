from __future__ import annotations

from app.config.settings import Settings
from app.persistence.db import safe_float, utc_now
from app.portfolio.constraints import build_cap_reasons, detect_static_conflicts, single_trade_cap
from app.portfolio.types import CandidateAllocation, PortfolioDecision, PortfolioState
from app.risk.types import RiskAssessment


class PortfolioAllocator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def compute_available_capital(
        self,
        state: PortfolioState,
        *,
        rollout_capital_limit: float | None = None,
    ) -> float:
        from app.portfolio.constraints import portfolio_total_headroom

        available = min(
            portfolio_total_headroom(self.settings, state),
            safe_float(state.free_cash),
            safe_float(rollout_capital_limit) if rollout_capital_limit is not None else safe_float(state.free_cash),
        )
        return safe_float(max(available, 0.0))

    def allocate_candidate(
        self,
        assessment: RiskAssessment,
        state: PortfolioState,
        *,
        score: float,
        ranking_index: int,
        execution_mode: str,
        rollout_capital_limit: float | None = None,
        preset_reasons: list[str] | None = None,
    ) -> PortfolioDecision:
        if not self.settings.portfolio_enabled:
            return self._build_decision(
                assessment=assessment,
                score=score,
                ranking_index=ranking_index,
                execution_mode=execution_mode,
                requested_capital=self._requested_capital(assessment),
                allocated_capital=self._requested_capital(assessment),
                decision="approved",
                reasons=[],
            )

        requested_capital = self._requested_capital(assessment)
        entry_price = self._entry_price(assessment)
        reasons = list(preset_reasons or [])
        reasons.extend(detect_static_conflicts(state, symbol=assessment.symbol, side=assessment.side))
        hard_reasons, headroom = build_cap_reasons(
            self.settings,
            state,
            symbol=assessment.symbol,
            strategy_name=assessment.strategy_name,
            requested_capital=requested_capital,
            rollout_capital_limit=rollout_capital_limit,
        )
        reasons.extend(hard_reasons)

        allowed_capital = min(
            requested_capital,
            safe_float(headroom["total_room"]),
            safe_float(headroom["strategy_room"]),
            safe_float(headroom["symbol_room"]),
            safe_float(headroom["cluster_room"]),
            safe_float(headroom["trade_room"]),
            safe_float(headroom["free_cash_room"]),
            safe_float(headroom["rollout_room"]),
        )
        allowed_capital = safe_float(max(allowed_capital, 0.0))

        if requested_capital > single_trade_cap(self.settings, state):
            reasons.append("single_trade_cap_exceeded")
        if requested_capital > safe_float(headroom["strategy_room"]) and safe_float(headroom["strategy_room"]) > 0:
            reasons.append("strategy_cap_applied")
        if requested_capital > safe_float(headroom["symbol_room"]) and safe_float(headroom["symbol_room"]) > 0:
            reasons.append("symbol_cap_applied")
        if requested_capital > safe_float(headroom["cluster_room"]) and safe_float(headroom["cluster_room"]) > 0:
            reasons.append("cluster_cap_applied")
        if requested_capital > safe_float(headroom["total_room"]) and safe_float(headroom["total_room"]) > 0:
            reasons.append("portfolio_total_cap_applied")

        if allowed_capital < self.settings.min_notional_value or entry_price <= 0:
            reasons.append("allocation_below_min_notional")
            allowed_capital = 0.0

        decision = "approved"
        allowed = True
        if any(reason in reasons for reason in {"conflicting_symbol_side", "max_open_positions_exceeded"}):
            allowed = False
            decision = "rejected"
            allowed_capital = 0.0
        elif allowed_capital <= 0:
            allowed = False
            decision = "rejected"
        elif allowed_capital < requested_capital:
            decision = "reduced"

        if reasons and decision == "approved":
            reasons = [item for item in reasons if item.endswith("_applied")]
        elif decision == "reduced":
            reasons = [item for item in reasons if item.endswith("_applied")] or ["allocation_reduced"]
        else:
            reasons = sorted(set(reasons))

        return self._build_decision(
            assessment=assessment,
            score=score,
            ranking_index=ranking_index,
            execution_mode=execution_mode,
            requested_capital=requested_capital,
            allocated_capital=allowed_capital,
            decision=decision,
            reasons=sorted(set(reasons)),
            cluster_name=str(headroom["cluster_name"]),
            allowed=allowed,
        )

    def allocate_batch(
        self,
        candidates: list[tuple[RiskAssessment, float]],
        state: PortfolioState,
        *,
        execution_mode: str,
        rollout_capital_limit: float | None = None,
        conflict_map: dict[str, list[str]] | None = None,
    ) -> list[PortfolioDecision]:
        from app.portfolio.state import PortfolioStateManager

        decisions: list[PortfolioDecision] = []
        state_manager = PortfolioStateManager(self.settings)
        for ranking_index, (assessment, score) in enumerate(candidates):
            decision = self.allocate_candidate(
                assessment,
                state,
                score=score,
                ranking_index=ranking_index,
                execution_mode=execution_mode,
                rollout_capital_limit=rollout_capital_limit,
                preset_reasons=(conflict_map or {}).get(assessment.assessment_id, []),
            )
            decisions.append(decision)
            state_manager.apply_candidate_allocation(
                state,
                CandidateAllocation(
                    assessment_id=decision.assessment_id,
                    symbol=decision.symbol,
                    strategy_name=decision.strategy_name,
                    side=decision.side,
                    requested_capital=decision.requested_capital,
                    allocated_capital=decision.allocated_capital,
                    allocated_quantity=decision.allocated_quantity,
                    score=decision.score,
                    decision=decision.decision,
                    reasons=list(decision.reasons),
                    cluster_name=decision.cluster_name,
                    execution_mode=execution_mode,
                ),
            )
        return decisions

    def _requested_capital(self, assessment: RiskAssessment) -> float:
        plan = assessment.generated_trade_plan
        requested = safe_float(
            assessment.notional_value
            or plan.get("notional_value")
            or safe_float(plan.get("entry_price")) * safe_float(plan.get("position_size"))
        )
        return requested

    def _entry_price(self, assessment: RiskAssessment) -> float:
        return safe_float(assessment.generated_trade_plan.get("entry_price")) or 0.0

    def _build_decision(
        self,
        *,
        assessment: RiskAssessment,
        score: float,
        ranking_index: int,
        execution_mode: str,
        requested_capital: float,
        allocated_capital: float,
        decision: str,
        reasons: list[str],
        cluster_name: str | None = None,
        allowed: bool | None = None,
    ) -> PortfolioDecision:
        entry_price = self._entry_price(assessment)
        allocated_quantity = safe_float(allocated_capital / entry_price) if entry_price > 0 else 0.0
        return PortfolioDecision(
            assessment_id=assessment.assessment_id,
            symbol=assessment.symbol,
            strategy_name=assessment.strategy_name,
            side=assessment.side,
            allowed=decision in {"approved", "reduced"} if allowed is None else allowed,
            decision=decision,
            allocated_capital=safe_float(allocated_capital),
            allocated_quantity=allocated_quantity,
            requested_capital=safe_float(requested_capital),
            score=safe_float(score),
            ranking_index=ranking_index,
            reasons=list(reasons),
            cluster_name=cluster_name,
            execution_mode=execution_mode,
            timestamp=utc_now(),
        )

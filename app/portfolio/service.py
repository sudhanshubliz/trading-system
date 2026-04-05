from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.config.settings import Settings, get_settings
from app.execution.types import Approval
from app.persistence.db import safe_float, utc_now
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.portfolio_repo import PortfolioRepository
from app.persistence.repositories.risk_repo import RiskRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.portfolio.allocator import PortfolioAllocator
from app.portfolio.constraints import summarize_denials
from app.portfolio.orchestrator import PortfolioOrchestrator
from app.portfolio.state import PortfolioStateManager, resolve_cluster
from app.portfolio.types import CandidateAllocation, PortfolioDecision, PortfolioState
from app.risk.types import RiskAssessment


class PortfolioService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        risk_repo: RiskRepository | None = None,
        approvals_repo: ApprovalsRepository | None = None,
        positions_repo: PositionsRepository | None = None,
        trades_repo: TradesRepository | None = None,
        portfolio_repo: PortfolioRepository | None = None,
        events_repo: EventsRepository | None = None,
        rollout_service: object | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.risk_repo = risk_repo
        self.approvals_repo = approvals_repo
        self.positions_repo = positions_repo
        self.trades_repo = trades_repo
        self.portfolio_repo = portfolio_repo
        self.events_repo = events_repo
        self.rollout_service = rollout_service
        self.state_manager = PortfolioStateManager(self.settings)
        self.allocator = PortfolioAllocator(self.settings)
        self.orchestrator = PortfolioOrchestrator(self.settings, self.allocator)

    def get_portfolio_state(self, execution_mode: str = "paper") -> PortfolioState:
        positions = self.positions_repo.list_open_positions(execution_mode) if self.positions_repo is not None else []
        trades = self.trades_repo.list_trades(execution_mode) if self.trades_repo is not None else []
        approvals = self.approvals_repo.list_pending(execution_mode) if self.approvals_repo is not None else []
        pending_allocations = self._build_pending_allocations(approvals)
        rollout_phase = self._rollout_phase_for_mode(execution_mode)
        return self.state_manager.build_state(
            positions=positions,
            trades=trades,
            approvals=approvals,
            pending_allocations=pending_allocations,
            active_rollout_phase=rollout_phase,
            execution_mode=execution_mode,
        )

    def get_allocations(self, execution_mode: str = "paper") -> dict[str, Any]:
        state = self.get_portfolio_state(execution_mode)
        return {
            "execution_mode": execution_mode,
            "deployed_capital": state.deployed_capital,
            "free_cash": state.free_cash,
            "reserved_cash": state.reserved_cash,
            "strategy_allocations": {key: asdict(value) for key, value in state.strategy_allocations.items()},
            "symbol_allocations": {key: asdict(value) for key, value in state.symbol_allocations.items()},
            "correlation_clusters": {key: asdict(value) for key, value in state.correlation_clusters.items()},
            "pending_candidate_count": state.pending_candidate_count,
            "rejected_candidate_count": state.rejected_candidate_count,
            "timestamp": state.timestamp,
        }

    def evaluate_candidates(
        self,
        assessment_ids: list[str],
        *,
        execution_mode: str = "paper",
    ) -> dict[str, Any]:
        state = self.get_portfolio_state(execution_mode)
        assessments = self._load_assessments(assessment_ids)
        decisions = self.orchestrator.select_candidates_for_execution(
            assessments,
            state,
            execution_mode=execution_mode,
            rollout_capital_limit=self._rollout_capital_limit(execution_mode),
        )
        for decision in decisions:
            self._persist_decision(decision)
        snapshot = self._persist_snapshot(state)
        return {
            "execution_mode": execution_mode,
            "state": state,
            "decisions": decisions,
            "selected_count": sum(1 for item in decisions if item.allowed),
            "rejected_count": sum(1 for item in decisions if not item.allowed),
            "denial_summary": summarize_denials([asdict(item) for item in decisions if not item.allowed]),
            "snapshot_id": snapshot,
            "timestamp": utc_now(),
        }

    def evaluate_live_candidate(
        self,
        assessment: RiskAssessment,
        order_request: Any,
    ) -> PortfolioDecision:
        state = self.get_portfolio_state("live")
        decisions = self.orchestrator.select_candidates_for_execution(
            [assessment],
            state,
            execution_mode="live",
            rollout_capital_limit=min(
                safe_float(getattr(order_request, "notional", 0.0)),
                self._rollout_capital_limit("live"),
            ),
        )
        decision = decisions[0]
        self._persist_decision(decision)
        return decision

    def rebalance_portfolio(self, execution_mode: str = "paper") -> dict[str, Any]:
        state = self.get_portfolio_state(execution_mode)
        actions: list[dict[str, Any]] = []
        if self.settings.portfolio_rebalance_enabled:
            strategy_cap = safe_float(state.total_equity * self.settings.portfolio_max_per_strategy_pct / 100.0)
            symbol_cap = safe_float(state.total_equity * self.settings.portfolio_max_per_symbol_pct / 100.0)
            for key, allocation in state.strategy_allocations.items():
                overflow = safe_float(allocation.deployed_capital - strategy_cap)
                if overflow > 0:
                    actions.append(
                        {
                            "scope": "strategy",
                            "scope_key": key,
                            "action": "reduce",
                            "excess_capital": overflow,
                        }
                    )
            for key, allocation in state.symbol_allocations.items():
                overflow = safe_float(allocation.deployed_capital - symbol_cap)
                if overflow > 0:
                    actions.append(
                        {
                            "scope": "symbol",
                            "scope_key": key,
                            "action": "reduce",
                            "excess_capital": overflow,
                        }
                    )
        payload = {
            "execution_mode": execution_mode,
            "enabled": self.settings.portfolio_rebalance_enabled,
            "actions": actions,
            "action_count": len(actions),
            "timestamp": utc_now(),
        }
        self._persist_record("portfolio_rebalance", payload, execution_mode=execution_mode, scope_key="rebalance")
        return payload

    def list_history(self, *, execution_mode: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if self.portfolio_repo is None:
            return []
        return self.portfolio_repo.list_records(execution_mode=execution_mode, limit=limit)

    def _build_pending_allocations(self, approvals: list[Approval]) -> list[CandidateAllocation]:
        items: list[CandidateAllocation] = []
        for approval in approvals:
            assessment = self.risk_repo.get_assessment(approval.assessment_id) if self.risk_repo is not None else None
            requested_capital = safe_float(assessment.notional_value) if assessment is not None else 0.0
            items.append(
                CandidateAllocation(
                    assessment_id=approval.assessment_id,
                    symbol=approval.symbol,
                    strategy_name=approval.strategy_name,
                    side=approval.side,
                    requested_capital=requested_capital,
                    allocated_capital=0.0,
                    allocated_quantity=0.0,
                    score=0.0,
                    decision="pending",
                    reasons=[],
                    cluster_name=resolve_cluster(approval.symbol, self.settings.portfolio_correlation_mode),
                    execution_mode=approval.execution_mode,
                )
            )
        return items

    def _load_assessments(self, assessment_ids: list[str]) -> list[RiskAssessment]:
        assessments: list[RiskAssessment] = []
        for assessment_id in assessment_ids:
            assessment = self.risk_repo.get_assessment(assessment_id) if self.risk_repo is not None else None
            if assessment is not None:
                assessments.append(assessment)
        return assessments

    def _rollout_phase_for_mode(self, execution_mode: str) -> str:
        if execution_mode != "live" or self.rollout_service is None:
            return "n/a" if execution_mode != "live" else "disabled"
        state = self.rollout_service.get_rollout_state()
        return str(getattr(state, "current_phase", "disabled"))

    def _rollout_capital_limit(self, execution_mode: str) -> float:
        if execution_mode != "live":
            return safe_float(self.settings.paper_account_start_balance)
        if self.rollout_service is None:
            return safe_float(self.settings.live_max_capital_total)
        state = self.rollout_service.get_rollout_state()
        return safe_float(getattr(state, "current_capital_limit", self.settings.live_max_capital_total))

    def _persist_decision(self, decision: PortfolioDecision) -> None:
        payload = asdict(decision)
        record_id = self._persist_record(
            "portfolio_decision",
            payload,
            execution_mode=decision.execution_mode,
            scope_key=decision.assessment_id,
        )
        event_type = "portfolio_candidate_allowed" if decision.allowed else "portfolio_candidate_denied"
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type=event_type,
                entity_id=decision.assessment_id,
                execution_mode=decision.execution_mode,
                symbol=decision.symbol,
                payload={**payload, "record_id": record_id},
            )

    def _persist_snapshot(self, state: PortfolioState) -> str | None:
        return self._persist_record(
            "portfolio_snapshot",
            asdict(state),
            execution_mode=state.execution_mode,
            scope_key="status",
        )

    def _persist_record(
        self,
        record_type: str,
        payload: dict[str, Any],
        *,
        execution_mode: str,
        scope_key: str,
    ) -> str | None:
        if self.portfolio_repo is None:
            return None
        return self.portfolio_repo.append_record(
            record_type=record_type,
            scope_key=scope_key,
            execution_mode=execution_mode,
            payload=payload,
        )

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

from app.config.settings import Settings
from app.execution.costs import calculate_fee, estimate_cost_aware_edge
from app.risk.position_sizing import (
    cap_position_size_by_notional,
    calculate_notional_value,
    calculate_position_size,
    calculate_reward_risk_ratio,
    calculate_risk_amount,
    calculate_stop_distance_abs,
    calculate_stop_distance_pct,
)
from app.risk.rules import (
    check_available_balance,
    check_concurrent_positions,
    check_confidence,
    check_cycle_throttle,
    check_daily_drawdown,
    check_market_data_health,
    check_net_edge_after_costs,
    check_open_risk_cap,
    check_position_size,
    check_positive_prices,
    check_reward_risk,
    check_risk_score,
    check_stop_distance,
    check_strategy_supported_side,
    check_turnover_cooldown,
    check_valid_side,
    check_weekly_drawdown,
)
from app.risk.types import AccountState, ExposureState, RiskAssessment, RiskCheckResult, RiskValidationInput


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RiskEngine:
    def __init__(self, settings: Settings, *, time_provider: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self.time_provider = time_provider or utc_now

    def assess(
        self,
        input_data: RiskValidationInput,
        account_state: AccountState,
        exposure_state: ExposureState,
        *,
        market_data_status: str | None = None,
        cycle_limit_passed: bool = True,
        turnover_cooldown_passed: bool = True,
    ) -> RiskAssessment:
        assessed_at = self.time_provider()
        assessment_id = self._build_assessment_id(input_data.signal_id)
        is_prediction_market = input_data.metadata.get("market_class") == "prediction_market"
        paper_only = bool(input_data.metadata.get("paper_only", False))

        stop_distance_abs = calculate_stop_distance_abs(input_data.entry_price, input_data.stop_loss)
        stop_distance_pct = calculate_stop_distance_pct(input_data.entry_price, input_data.stop_loss)
        effective_stop_distance = stop_distance_abs * (1 + (self.settings.max_slippage_pct / 100))
        risk_amount = calculate_risk_amount(
            account_state.available_balance,
            self.settings.max_risk_per_trade_pct,
        )
        uncapped_position_size = calculate_position_size(
            risk_amount,
            effective_stop_distance,
            precision=self.settings.position_size_precision,
        )
        max_position_notional = self._resolve_max_position_notional(account_state.available_balance)
        if is_prediction_market:
            requested_notional = self._metadata_float(
                input_data.metadata,
                "order_notional_usd",
                self.settings.latency_arb_paper_order_notional_usd,
            )
            max_position_notional = min(
                max_position_notional,
                max(requested_notional, self.settings.min_notional_value),
            )
        position_size = cap_position_size_by_notional(
            input_data.entry_price,
            uncapped_position_size,
            max_position_notional,
            precision=self.settings.position_size_precision,
        )
        notional_value = (
            calculate_notional_value(input_data.entry_price, position_size)
            if position_size is not None
            else None
        )
        effective_risk_amount = (
            round(position_size * effective_stop_distance, 6)
            if position_size is not None
            else 0.0
        )
        edge = estimate_cost_aware_edge(
            entry_price=input_data.entry_price,
            stop_loss=input_data.stop_loss,
            target_price=input_data.target_1,
            confidence=input_data.confidence_score / 100.0,
            fee_bps_per_side=self.settings.paper_execution_fee_bps,
            slippage_bps_per_side=self.settings.paper_execution_base_slippage_bps,
        )
        gross_expected_edge_bps = edge.gross_expected_edge_bps
        round_trip_fee_bps = edge.round_trip_fee_bps
        round_trip_slippage_bps = edge.round_trip_slippage_bps
        net_edge_after_costs_bps = edge.net_edge_after_costs_bps
        if is_prediction_market:
            gross_expected_edge_bps = self._metadata_float(
                input_data.metadata,
                "gross_expected_edge_bps",
                gross_expected_edge_bps,
            )
            round_trip_fee_bps = self._metadata_float(
                input_data.metadata,
                "estimated_fee_bps",
                round_trip_fee_bps,
            )
            round_trip_slippage_bps = self._metadata_float(
                input_data.metadata,
                "estimated_slippage_bps",
                round_trip_slippage_bps,
            )
            net_edge_after_costs_bps = self._metadata_float(
                input_data.metadata,
                "net_edge_after_costs_bps",
                gross_expected_edge_bps - round_trip_fee_bps - round_trip_slippage_bps,
            )
        estimated_round_trip_cost_bps = round_trip_fee_bps + round_trip_slippage_bps
        estimated_fee = (
            calculate_fee(notional_value, round_trip_fee_bps)
            if notional_value is not None
            else None
        )
        actual_reward_risk_ratio = calculate_reward_risk_ratio(
            input_data.entry_price,
            input_data.stop_loss,
            input_data.target_1,
            input_data.side,
        )
        open_risk_pct_after = (
            exposure_state.open_risk_pct + ((effective_risk_amount / account_state.balance) * 100)
            if account_state.balance > 0
            else None
        )

        risk_score = self._calculate_risk_score(
            stop_distance_pct=stop_distance_pct,
            reward_risk_ratio=actual_reward_risk_ratio,
            confidence_score=input_data.confidence_score,
        )
        trade_classification = self._classify_trade(risk_score)

        checks: list[RiskCheckResult] = [
            check_valid_side(input_data.side),
            check_strategy_supported_side(input_data.strategy_name, input_data.side),
            check_positive_prices(input_data.entry_price, input_data.stop_loss, input_data.target_1),
            check_stop_distance(
                stop_distance_pct,
                min_stop_distance_pct=self.settings.min_stop_distance_pct,
                max_stop_distance_pct=self.settings.max_stop_distance_pct,
            ),
            check_confidence(input_data.confidence_score, self.settings.min_confidence_score),
            check_reward_risk(actual_reward_risk_ratio, self.settings.min_reward_risk_ratio),
            check_available_balance(account_state.available_balance),
            check_position_size(
                position_size,
                notional_value,
                min_notional_value=self.settings.min_notional_value,
                max_notional_value=max_position_notional,
            ),
            check_daily_drawdown(
                self._drawdown_pct(account_state.balance, account_state.realized_pnl_daily),
                self.settings.max_daily_drawdown_pct,
            ),
            check_weekly_drawdown(
                self._drawdown_pct(account_state.balance, account_state.realized_pnl_weekly),
                self.settings.max_weekly_drawdown_pct,
            ),
            check_concurrent_positions(
                exposure_state.open_positions,
                self.settings.max_concurrent_positions,
            ),
            check_open_risk_cap(
                open_risk_pct_after,
                self.settings.max_open_risk_pct,
            ),
            check_market_data_health(market_data_status),
            check_risk_score(risk_score),
            check_cycle_throttle(cycle_limit_passed),
            check_net_edge_after_costs(
                net_edge_after_costs_bps,
                enabled=self.settings.enable_cost_aware_trade_filter,
                minimum_bps=self.settings.min_net_edge_after_costs_bps,
            ),
            check_turnover_cooldown(
                enabled=self.settings.strategy_trade_cooldown_minutes > 0,
                passed=turnover_cooldown_passed,
            ),
        ]
        if is_prediction_market:
            prediction_paper_gate_passed = not (
                paper_only and self.settings.execution_mode not in {"paper", "shadow"}
            )
            checks.append(
                RiskCheckResult(
                    name="prediction_market_paper_only_gate",
                    passed=prediction_paper_gate_passed,
                    details=None if prediction_paper_gate_passed else "prediction_market_strategy_is_paper_only",
                )
            )

        rejection_reasons = [check.details for check in checks if not check.passed and check.details is not None]
        final_decision = "approved_for_review" if not rejection_reasons else "rejected"

        generated_trade_plan: dict[str, float | str | bool | None] = {
            "symbol": input_data.symbol,
            "side": input_data.side,
            "entry_price": input_data.entry_price,
            "stop_loss": input_data.stop_loss,
            "target_1": input_data.target_1,
            "target_2": input_data.target_2,
            "position_size": position_size,
            "notional_value": notional_value,
            "risk_amount": effective_risk_amount,
            "gross_expected_edge_bps": gross_expected_edge_bps,
            "estimated_round_trip_cost_bps": estimated_round_trip_cost_bps,
            "net_edge_after_costs_bps": net_edge_after_costs_bps,
            "round_trip_fee_bps": round_trip_fee_bps,
            "round_trip_slippage_bps": round_trip_slippage_bps,
            "max_position_notional": max_position_notional,
            "notional_capped": bool(
                uncapped_position_size is not None
                and position_size is not None
                and position_size < uncapped_position_size
            ),
            "mode": self.settings.execution_mode,
            "approved_for_review": final_decision == "approved_for_review",
        }
        if is_prediction_market:
            generated_trade_plan.update(
                {
                    "market_class": "prediction_market",
                    "paper_only": paper_only,
                    "market_id": str(input_data.metadata.get("market_id") or ""),
                    "condition_id": str(input_data.metadata.get("condition_id") or ""),
                    "token_id": str(input_data.metadata.get("token_id") or ""),
                    "outcome": str(input_data.metadata.get("outcome") or ""),
                    "fee_model": "polymarket_probability",
                    "fee_rate": self._metadata_float(input_data.metadata, "fee_rate", 0.0),
                }
            )

        passed_checks_count = sum(1 for check in checks if check.passed)
        failed_checks_count = len(checks) - passed_checks_count

        return RiskAssessment(
            assessment_id=assessment_id,
            signal_id=input_data.signal_id,
            symbol=input_data.symbol,
            side=input_data.side,
            strategy_name=input_data.strategy_name,
            final_decision=final_decision,
            account_balance=account_state.balance,
            max_risk_pct=self.settings.max_risk_per_trade_pct,
            risk_amount=effective_risk_amount,
            stop_distance_abs=stop_distance_abs,
            stop_distance_pct=stop_distance_pct,
            position_size=position_size,
            notional_value=notional_value,
            estimated_fee=estimated_fee,
            estimated_slippage_pct=round(round_trip_slippage_bps / 100.0, 6),
            open_risk_pct_before=exposure_state.open_risk_pct,
            open_risk_pct_after=open_risk_pct_after,
            daily_drawdown_pct=self._drawdown_pct(account_state.balance, account_state.realized_pnl_daily),
            weekly_drawdown_pct=self._drawdown_pct(account_state.balance, account_state.realized_pnl_weekly),
            min_reward_risk_ratio=self.settings.min_reward_risk_ratio,
            actual_reward_risk_ratio=actual_reward_risk_ratio,
            confidence_threshold=self.settings.min_confidence_score,
            risk_score=risk_score,
            trade_classification=trade_classification,
            passed_checks_count=passed_checks_count,
            failed_checks_count=failed_checks_count,
            checks=checks,
            rejection_reasons=rejection_reasons,
            generated_trade_plan=generated_trade_plan,
            assessed_at=assessed_at,
        )

    def _build_assessment_id(self, signal_id: str) -> str:
        digest = hashlib.sha1(signal_id.encode("utf-8")).hexdigest()
        return f"ras_{digest[:12]}"

    def _calculate_risk_score(
        self,
        *,
        stop_distance_pct: float,
        reward_risk_ratio: float | None,
        confidence_score: int,
    ) -> int:
        if reward_risk_ratio is None:
            return 0

        stop_score = 1.0 if self.settings.min_stop_distance_pct <= stop_distance_pct <= 2.5 else 0.5
        reward_score = min(reward_risk_ratio / max(self.settings.min_reward_risk_ratio, 0.01), 1.5) / 1.5
        confidence_score_unit = max(0.0, min(confidence_score / 100, 1.0))
        score = int(round((stop_score * 30) + (reward_score * 35) + (confidence_score_unit * 35)))
        return max(0, min(score, 100))

    def _classify_trade(self, risk_score: int) -> str:
        if risk_score > 80:
            return "A+"
        if risk_score >= 70:
            return "A"
        if risk_score >= 60:
            return "B"
        return "Reject"

    def _drawdown_pct(self, balance: float, realized_pnl: float) -> float:
        if balance <= 0:
            return 0.0
        return abs(min(realized_pnl, 0.0)) / balance * 100

    def _resolve_max_position_notional(self, available_balance: float) -> float:
        if self.settings.execution_mode == "paper":
            return max(
                available_balance * (self.settings.paper_max_position_notional_pct_of_balance / 100),
                self.settings.min_notional_value,
            )

        return max(available_balance * 3, self.settings.min_notional_value)

    def _metadata_float(
        self,
        metadata: dict[str, object],
        key: str,
        default: float,
    ) -> float:
        value = metadata.get(key)
        try:
            return float(value) if value is not None else float(default)
        except (TypeError, ValueError):
            return float(default)

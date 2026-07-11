from __future__ import annotations

from app.risk.types import RiskCheckResult


LONG_ONLY_STRATEGIES: set[str] = set()


def check_valid_side(side: str) -> RiskCheckResult:
    passed = side.lower() in {"long", "short"}
    return RiskCheckResult(
        name="valid_side",
        passed=passed,
        details=None if passed else "side_must_be_long_or_short",
    )


def check_strategy_supported_side(strategy_name: str, side: str) -> RiskCheckResult:
    passed = not (strategy_name in LONG_ONLY_STRATEGIES and side.lower() != "long")
    return RiskCheckResult(
        name="strategy_side_supported",
        passed=passed,
        details=None if passed else "side_not_supported_by_strategy",
    )


def check_positive_prices(entry_price: float, stop_loss: float, target_1: float) -> RiskCheckResult:
    passed = entry_price > 0 and stop_loss > 0 and target_1 > 0
    return RiskCheckResult(
        name="positive_prices",
        passed=passed,
        details=None if passed else "entry_stop_target_must_be_positive",
    )


def check_confidence(confidence_score: int, min_confidence_score: int) -> RiskCheckResult:
    passed = confidence_score >= min_confidence_score
    return RiskCheckResult(
        name="confidence_passed",
        passed=passed,
        details=None if passed else "confidence_below_threshold",
    )


def check_reward_risk(
    actual_reward_risk_ratio: float | None,
    min_reward_risk_ratio: float,
) -> RiskCheckResult:
    passed = actual_reward_risk_ratio is not None and actual_reward_risk_ratio >= min_reward_risk_ratio
    return RiskCheckResult(
        name="reward_risk_passed",
        passed=passed,
        details=None if passed else "reward_risk_below_minimum",
    )


def check_stop_distance(
    stop_distance_pct: float,
    *,
    min_stop_distance_pct: float,
    max_stop_distance_pct: float,
) -> RiskCheckResult:
    passed = min_stop_distance_pct <= stop_distance_pct <= max_stop_distance_pct
    return RiskCheckResult(
        name="stop_distance_valid",
        passed=passed,
        details=None if passed else "stop_distance_out_of_bounds",
    )


def check_position_size(
    position_size: float | None,
    notional_value: float | None,
    *,
    min_notional_value: float,
    max_notional_value: float,
) -> RiskCheckResult:
    passed = (
        position_size is not None
        and position_size > 0
        and notional_value is not None
        and notional_value >= min_notional_value
        and notional_value <= max_notional_value
    )
    return RiskCheckResult(
        name="position_size_valid",
        passed=passed,
        details=None if passed else "position_size_or_notional_invalid",
    )


def check_daily_drawdown(
    daily_drawdown_pct: float,
    max_daily_drawdown_pct: float,
) -> RiskCheckResult:
    passed = daily_drawdown_pct < max_daily_drawdown_pct
    return RiskCheckResult(
        name="daily_drawdown_passed",
        passed=passed,
        details=None if passed else "daily_drawdown_limit_breached",
    )


def check_weekly_drawdown(
    weekly_drawdown_pct: float,
    max_weekly_drawdown_pct: float,
) -> RiskCheckResult:
    passed = weekly_drawdown_pct < max_weekly_drawdown_pct
    return RiskCheckResult(
        name="weekly_drawdown_passed",
        passed=passed,
        details=None if passed else "weekly_drawdown_limit_breached",
    )


def check_concurrent_positions(
    open_positions: int,
    max_concurrent_positions: int,
) -> RiskCheckResult:
    passed = open_positions < max_concurrent_positions
    return RiskCheckResult(
        name="concurrent_positions_passed",
        passed=passed,
        details=None if passed else "max_concurrent_positions_reached",
    )


def check_open_risk_cap(
    open_risk_pct_after: float | None,
    max_open_risk_pct: float,
) -> RiskCheckResult:
    passed = open_risk_pct_after is not None and open_risk_pct_after <= max_open_risk_pct
    return RiskCheckResult(
        name="open_risk_cap_passed",
        passed=passed,
        details=None if passed else "open_risk_cap_exceeded",
    )


def check_available_balance(available_balance: float) -> RiskCheckResult:
    passed = available_balance > 0
    return RiskCheckResult(
        name="available_balance_passed",
        passed=passed,
        details=None if passed else "available_balance_depleted",
    )


def check_market_data_health(status: str | None) -> RiskCheckResult:
    passed = status in {None, "ok"}
    return RiskCheckResult(
        name="market_data_health_passed",
        passed=passed,
        details=None if passed else "market_data_not_healthy",
    )


def check_risk_score(risk_score: int) -> RiskCheckResult:
    passed = risk_score >= 60
    return RiskCheckResult(
        name="risk_score_passed",
        passed=passed,
        details=None if passed else "risk_score_below_threshold",
    )


def check_cycle_throttle(passed: bool) -> RiskCheckResult:
    return RiskCheckResult(
        name="evaluation_cycle_limit_passed",
        passed=passed,
        details=None if passed else "evaluation_cycle_limit_reached",
    )


def check_net_edge_after_costs(
    net_edge_bps: float,
    *,
    enabled: bool,
    minimum_bps: float,
) -> RiskCheckResult:
    passed = not enabled or net_edge_bps >= minimum_bps
    return RiskCheckResult(
        name="net_edge_after_costs_passed",
        passed=passed,
        details=None if passed else "net_edge_after_costs_below_minimum",
    )


def check_turnover_cooldown(*, enabled: bool, passed: bool) -> RiskCheckResult:
    effective_passed = not enabled or passed
    return RiskCheckResult(
        name="strategy_turnover_cooldown_passed",
        passed=effective_passed,
        details=None if effective_passed else "strategy_turnover_cooldown_active",
    )

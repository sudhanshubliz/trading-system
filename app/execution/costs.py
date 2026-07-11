from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CostAwareEdge:
    risk_bps: float
    reward_bps: float
    gross_expected_edge_bps: float
    round_trip_fee_bps: float
    round_trip_slippage_bps: float
    estimated_round_trip_cost_bps: float
    net_edge_after_costs_bps: float


def calculate_fee(notional: float, fee_bps: float) -> float:
    if notional <= 0 or fee_bps <= 0:
        return 0.0
    return abs(notional) * fee_bps / 10000.0


def calculate_prediction_market_fee(*, shares: float, price: float, fee_rate: float) -> float:
    """Return the Polymarket-style taker fee for a binary outcome fill."""
    bounded_price = max(0.0, min(price, 1.0))
    return max(shares, 0.0) * max(fee_rate, 0.0) * bounded_price * (1.0 - bounded_price)


def apply_exit_slippage(price: float, *, side: str, slippage_bps: float) -> float:
    if price <= 0 or slippage_bps <= 0:
        return price
    if side.lower() == "long":
        return price * (1.0 - slippage_bps / 10000.0)
    if side.lower() == "short":
        return price * (1.0 + slippage_bps / 10000.0)
    return price


def estimate_cost_aware_edge(
    *,
    entry_price: float,
    stop_loss: float,
    target_price: float,
    confidence: float,
    fee_bps_per_side: float,
    slippage_bps_per_side: float,
) -> CostAwareEdge:
    if entry_price <= 0:
        risk_bps = 0.0
        reward_bps = 0.0
    else:
        risk_bps = abs(entry_price - stop_loss) / entry_price * 10000.0
        reward_bps = abs(target_price - entry_price) / entry_price * 10000.0
    win_probability = max(0.0, min(confidence, 1.0))
    gross_edge = (win_probability * reward_bps) - ((1.0 - win_probability) * risk_bps)
    round_trip_fee = max(fee_bps_per_side, 0.0) * 2.0
    round_trip_slippage = max(slippage_bps_per_side, 0.0) * 2.0
    total_cost = round_trip_fee + round_trip_slippage
    return CostAwareEdge(
        risk_bps=round(risk_bps, 6),
        reward_bps=round(reward_bps, 6),
        gross_expected_edge_bps=round(gross_edge, 6),
        round_trip_fee_bps=round(round_trip_fee, 6),
        round_trip_slippage_bps=round(round_trip_slippage, 6),
        estimated_round_trip_cost_bps=round(total_cost, 6),
        net_edge_after_costs_bps=round(gross_edge - total_cost, 6),
    )

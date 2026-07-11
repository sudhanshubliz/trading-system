from __future__ import annotations

import math

from app.execution.costs import calculate_prediction_market_fee
from app.polymarket.types import PolymarketBookLevel
from app.probability.bayesian_model import update_probability
from app.probability.types import ProbabilityEvidence
from app.strategies.latency_arbitrage.crypto_reference_model import ReferenceState
from app.strategies.latency_arbitrage.polymarket_mapping import LatencyArbMarketMapping


def estimate_fair_probability(
    mapping: LatencyArbMarketMapping,
    state: ReferenceState,
    *,
    seconds_to_expiry: float,
) -> tuple[float, dict[str, object]]:
    if mapping.threshold is None or seconds_to_expiry <= 0:
        base_probability = 0.5
    else:
        distance_pct = ((state.current_price - mapping.threshold) / max(mapping.threshold, 1e-9)) * 100.0
        horizon_vol_pct = max(
            state.realized_volatility_pct * math.sqrt(max(seconds_to_expiry, 60.0) / 300.0),
            0.05,
        )
        z_score = distance_pct / horizon_vol_pct
        if mapping.direction == "down":
            z_score *= -1.0
        base_probability = 1.0 / (1.0 + math.exp(-max(min(z_score, 20.0), -20.0)))
    update = update_probability(
        prior=base_probability,
        evidence=[
            ProbabilityEvidence(
                source_name="binance_30s",
                direction_bias=_signed_bias(state.return_30s_pct),
                confidence=min(abs(state.return_30s_pct) / 0.35, 1.0),
                weight=0.5,
            ),
            ProbabilityEvidence(
                source_name="binance_1m",
                direction_bias=_signed_bias(state.return_1m_pct),
                confidence=min(abs(state.return_1m_pct) / 0.55, 1.0),
                weight=0.75,
            ),
            ProbabilityEvidence(
                source_name="binance_5m",
                direction_bias=_signed_bias(state.return_5m_pct),
                confidence=min(abs(state.return_5m_pct) / 0.9, 1.0),
                weight=1.0,
            ),
        ],
    )
    return update.posterior, {
        "prior_probability": round(base_probability, 6),
        "posterior_probability": round(update.posterior, 6),
        "effective_confidence": update.effective_confidence,
        "contributions": update.contributions,
    }


def estimate_edge_bps(
    *,
    fair_probability: float,
    market_probability: float,
    depth_usd: float,
    spread_bps: float | None,
    execution_price: float | None = None,
    book_asks: list[PolymarketBookLevel] | None = None,
    order_notional_usd: float = 50.0,
    fee_rate: float = 0.0,
    execution_buffer_bps: float = 25.0,
) -> dict[str, float]:
    resolved_execution_price = execution_price or market_probability
    fill_price = resolved_execution_price
    fill_ratio = 1.0
    shares = order_notional_usd / max(resolved_execution_price, 1e-9)
    book_slippage_bps = 0.0
    if book_asks:
        fill = walk_asks_for_notional(book_asks, order_notional_usd)
        fill_price = fill["fill_price"]
        fill_ratio = fill["fill_ratio"]
        shares = fill["shares"]
        book_slippage_bps = fill["slippage_bps"]

    gross_edge_bps = max((fair_probability - fill_price) * 10000.0, 0.0)
    entry_fee = calculate_prediction_market_fee(shares=shares, price=fill_price, fee_rate=fee_rate)
    exit_fee = calculate_prediction_market_fee(shares=shares, price=fair_probability, fee_rate=fee_rate)
    fee_estimate_bps = ((entry_fee + exit_fee) / max(order_notional_usd * fill_ratio, 1e-9)) * 10000.0
    fallback_spread_penalty = 0.0 if book_asks else max((spread_bps or 0.0) * 0.5, 0.0)
    slippage_estimate_bps = book_slippage_bps + fallback_spread_penalty + max(execution_buffer_bps, 0.0)
    if not book_asks:
        slippage_estimate_bps += max(3.0, 8000.0 / max(depth_usd, 1.0))
    net_edge_bps = gross_edge_bps - fee_estimate_bps - slippage_estimate_bps
    return {
        "gross_edge_bps": round(gross_edge_bps, 6),
        "fee_estimate_bps": round(fee_estimate_bps, 6),
        "slippage_estimate_bps": round(slippage_estimate_bps, 6),
        "net_edge_bps": round(net_edge_bps, 6),
        "simulated_fill_price": round(fill_price, 8),
        "fill_ratio": round(fill_ratio, 6),
        "estimated_shares": round(shares, 6),
        "entry_fee_usd": round(entry_fee, 6),
        "exit_fee_usd": round(exit_fee, 6),
    }


def walk_asks_for_notional(
    asks: list[PolymarketBookLevel],
    order_notional_usd: float,
) -> dict[str, float]:
    ordered = sorted(
        [item for item in asks if item.price > 0 and item.size > 0],
        key=lambda item: item.price,
    )
    requested = max(order_notional_usd, 0.0)
    if not ordered or requested <= 0:
        return {"fill_price": 0.0, "fill_ratio": 0.0, "shares": 0.0, "slippage_bps": 0.0}
    remaining = requested
    shares = 0.0
    spent = 0.0
    for level in ordered:
        level_notional = level.price * level.size
        used_notional = min(remaining, level_notional)
        used_shares = used_notional / level.price
        shares += used_shares
        spent += used_notional
        remaining -= used_notional
        if remaining <= 1e-9:
            break
    fill_ratio = spent / requested
    fill_price = spent / shares if shares > 0 else 0.0
    top_price = ordered[0].price
    slippage_bps = max((fill_price - top_price) / max(top_price, 1e-9) * 10000.0, 0.0)
    return {
        "fill_price": fill_price,
        "fill_ratio": fill_ratio,
        "shares": shares,
        "slippage_bps": slippage_bps,
    }


def _signed_bias(value: float) -> float:
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0

from __future__ import annotations

import math

from app.probability.bayesian_model import update_probability
from app.probability.types import ProbabilityEvidence
from app.strategies.latency_arbitrage.crypto_reference_model import ReferenceState
from app.strategies.latency_arbitrage.polymarket_mapping import LatencyArbMarketMapping


def estimate_fair_probability(mapping: LatencyArbMarketMapping, state: ReferenceState, *, seconds_to_expiry: float) -> tuple[float, dict[str, object]]:
    if mapping.threshold is None or seconds_to_expiry <= 0:
        base_probability = 0.5
    else:
        distance_pct = ((state.current_price - mapping.threshold) / max(mapping.threshold, 1e-9)) * 100.0
        horizon_vol_pct = max(state.realized_volatility_pct * math.sqrt(max(seconds_to_expiry, 60.0) / 300.0), 0.05)
        z_score = distance_pct / horizon_vol_pct
        if mapping.direction == "down":
            z_score *= -1.0
        base_probability = 1.0 / (1.0 + math.exp(-z_score))
    update = update_probability(
        prior=base_probability,
        evidence=[
            ProbabilityEvidence(source_name="binance_30s", direction_bias=_signed_bias(state.return_30s_pct), confidence=min(abs(state.return_30s_pct) / 0.35, 1.0), weight=0.5),
            ProbabilityEvidence(source_name="binance_1m", direction_bias=_signed_bias(state.return_1m_pct), confidence=min(abs(state.return_1m_pct) / 0.55, 1.0), weight=0.75),
            ProbabilityEvidence(source_name="binance_5m", direction_bias=_signed_bias(state.return_5m_pct), confidence=min(abs(state.return_5m_pct) / 0.9, 1.0), weight=1.0),
        ],
    )
    return update.posterior, {
        "prior_probability": round(base_probability, 6),
        "posterior_probability": round(update.posterior, 6),
        "effective_confidence": update.effective_confidence,
        "contributions": update.contributions,
    }


def estimate_edge_bps(*, fair_probability: float, market_probability: float, depth_usd: float, spread_bps: float | None) -> dict[str, float]:
    probability_gap = fair_probability - market_probability
    gross_edge_bps = abs(probability_gap) * 10000.0
    fee_estimate_bps = 10.0
    slippage_estimate_bps = max(3.0, 8000.0 / max(depth_usd, 1.0)) + max((spread_bps or 0.0) * 0.25, 0.0)
    net_edge_bps = gross_edge_bps - fee_estimate_bps - slippage_estimate_bps
    return {
        "gross_edge_bps": round(gross_edge_bps, 6),
        "fee_estimate_bps": round(fee_estimate_bps, 6),
        "slippage_estimate_bps": round(slippage_estimate_bps, 6),
        "net_edge_bps": round(net_edge_bps, 6),
    }


def _signed_bias(value: float) -> float:
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0

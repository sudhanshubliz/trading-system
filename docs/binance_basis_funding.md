# Binance Basis / Funding Engine

## Scope

Phase 2 adds a Binance basis/funding engine in `app/arbitrage`.

It evaluates:

- raw spot vs perp basis in bps
- annualized basis approximation
- basis z-score from recent history
- funding extremes and funding z-score
- tradability after fees, slippage, liquidity, and staleness checks

## Output Contract

Each opportunity is stored and exposed as a structured `basis_funding` object with:

- `id`
- `symbol`
- `timestamp`
- `basis_value`
- `funding_value`
- `basis_zscore`
- `funding_zscore`
- `gross_edge_estimate`
- `fee_estimate`
- `slippage_estimate`
- `net_edge_estimate`
- `confidence`
- `recommended_direction`
- `expected_holding_period`
- `tradable`
- `explanation`
- `metadata`

## Opportunity Classes

- `none`
- `monitor`
- `actionable_long_basis_reversion`
- `actionable_short_basis_reversion`
- `carry_like_positive`
- `carry_like_negative`

## Persistence And APIs

- persisted in `arbitrage_opportunities`
- emitted into `alpha_source_readings` as `source_name=basis_funding`
- queried via `GET /api/v1/arbitrage/opportunities`

Supported filters:

- `symbol`
- `tradable`
- `confidence`
- `recency_seconds`

## Safety Notes

- opportunities are not orders
- stale or missing funding / order-book inputs mark opportunities non-tradable
- low net edge after fees and slippage is vetoed before an opportunity is marked tradable
- guarded live semantics are unchanged

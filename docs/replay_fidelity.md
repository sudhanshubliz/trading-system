# Replay Fidelity

## What Phase 2 Replay Adds

Replay now produces:

- basis/funding opportunities
- microstructure snapshots
- risk veto outcomes
- execution-quality records
- fidelity notes on each replay run

## Fidelity Boundaries

Replay is intentionally honest about what it can and cannot reconstruct.

Supported well:

- candle-driven signal generation
- close-boundary candle visibility without bar-level lookahead
- deterministic spot vs perp basis approximation
- deterministic synthetic order-book and trade-flow views
- repeatable risk-lock evaluation
- repeatable simulated execution-quality scoring
- native two-sided fee accounting and deterministic adverse fill slippage

Not fully reconstructable from candle-only inputs:

- raw exchange queue position
- exact venue latency
- true order-book event sequencing
- exact historical funding snapshots when they were never stored

## Current Approach

- if replay futures candles are provided, basis/funding uses those directly
- if native historical funding snapshots are absent, funding is approximated from spot-vs-perp relationships
- microstructure is synthesized from candle path, range, and volume
- a candle's completed OHLC becomes available only at `open_time + timeframe`; higher-timeframe bars remain hidden until their own close
- entry and exit fees are deducted from net P&L, while adverse slippage is embedded in simulated fill prices and exposed separately as attribution
- replay outputs include `fidelity_notes` so downstream consumers do not over-interpret the results

## Walk-Forward Evidence

`scripts/run_binance_walk_forward.py` runs a fixed configuration over at least 90 days and divides the completed trades into chronological folds. It does not select parameters between folds, claim order-book queue precision, or promote a strategy automatically.

The gate records duration, sample count, native after-cost expectancy, profit factor, drawdown, and positive-fold count. A failed gate is a live-trading blocker. A passed replay gate is only permission to continue collecting shadow evidence, not permission to trade live.

## Recommendation

Use replay for:

- regression testing
- deterministic signal comparisons
- risk-lock validation
- execution-quality trend analysis

Do not use candle-only replay as proof of exchange-grade microstructure fill performance.

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
- deterministic spot vs perp basis approximation
- deterministic synthetic order-book and trade-flow views
- repeatable risk-lock evaluation
- repeatable simulated execution-quality scoring

Not fully reconstructable from candle-only inputs:

- raw exchange queue position
- exact venue latency
- true order-book event sequencing
- exact historical funding snapshots when they were never stored

## Current Approach

- if replay futures candles are provided, basis/funding uses those directly
- if native historical funding snapshots are absent, funding is approximated from spot-vs-perp relationships
- microstructure is synthesized from candle path, range, and volume
- replay outputs include `fidelity_notes` so downstream consumers do not over-interpret the results

## Recommendation

Use replay for:

- regression testing
- deterministic signal comparisons
- risk-lock validation
- execution-quality trend analysis

Do not use candle-only replay as proof of exchange-grade microstructure fill performance.

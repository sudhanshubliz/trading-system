# Portfolio Correlation

The portfolio brain now applies explainable bucket-based correlation throttles instead of assuming all fused scores are independent.

## Current Buckets

- `crypto_directional`
- `crypto_carry`
- `microstructure_short_horizon`
- `event_markets`
- `wallet_follow`
- `news_event_reaction`

## What The Allocator Does

- groups fused opportunities into coarse risk buckets
- caps correlated bucket exposure with config-driven limits
- throttles strategy weights when bucket caps are breached
- records why a throttle or cap was applied in snapshot explanations and metadata

The model is intentionally simple and explainable. It is meant to reduce concentration risk without pretending to estimate perfect correlation matrices from sparse or unstable inputs.

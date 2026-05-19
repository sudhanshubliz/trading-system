# Polymarket Real Provider

The Polymarket provider now supports three safe modes:

- `mock`
- `real`
- `auto_fallback`

`auto_fallback` uses the real provider first and degrades to the mock provider only in explicit local/dev contexts when the real feed is unavailable or incomplete.

## Supported Methods

- `list_markets`
- `get_market`
- `get_orderbook`
- `get_market_prices`
- `get_recent_trades`
- `get_linked_markets`
- `health_check`

## Normalization

The real adapter normalizes public payloads into:

- internal market metadata
- yes/no prices
- order-book depth and spread
- market status and timestamps
- source diagnostics

## Safety

- stale-data-aware health checks
- graceful degradation instead of hard crashes
- provider ingest runs persisted through provider health
- mispricing logic remains unchanged and works on both mock and real-normalized data

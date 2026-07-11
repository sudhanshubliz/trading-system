# Polymarket Real Provider

## Purpose

The real provider is a read-only market-data integration. It does not load wallet private keys, derive CLOB trading credentials, sign messages, or place orders.

The adapter uses separate public interfaces:

- Gamma API for active market metadata, outcomes, token IDs, status, liquidity, and timestamps
- CLOB REST for complete YES and NO order books
- CLOB market WebSocket for incremental book and price updates
- Data API for recent public trades when available

Normalized data is consumed by the existing pipeline:

```text
Polymarket/Binance data
  -> latency or mispricing research
  -> StrategyOwnerService
  -> RiskService
  -> explicit approval
  -> paper/shadow execution only
```

No Polymarket strategy has a direct execution call.

## Modes

```dotenv
POLYMARKET_PROVIDER_MODE=mock
```

- `mock`: deterministic local fixtures. Mock-derived latency candidates are never tradable.
- `real`: public Polymarket data only. Failures degrade provider health and do not stop the Binance core.
- `auto_fallback`: tries real first and may use mock only in explicit development/test or local deployment mode. Fallback data remains identifiable as mock.

`*_PROVIDER_MODE` is authoritative. The legacy `POLYMARKET_PROVIDER` field remains accepted for backward compatibility.

## Endpoints And Stream

```dotenv
POLYMARKET_BASE_URL=https://gamma-api.polymarket.com
POLYMARKET_CLOB_BASE_URL=https://clob.polymarket.com
POLYMARKET_DATA_BASE_URL=https://data-api.polymarket.com
POLYMARKET_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market
POLYMARKET_TIMEOUT_MS=3000
POLYMARKET_MARKET_LIMIT=500
POLYMARKET_BOOK_DEPTH_LEVELS=10
POLYMARKET_STREAM_ENABLED=true
POLYMARKET_STREAM_MAX_ASSETS=40
POLYMARKET_STREAM_STALE_SECONDS=15
```

The stream subscribes only to a bounded set of assets, prioritizing BTC/ETH-related markets and then liquidity. It reconnects with bounded exponential backoff and uses the documented `PING`/`PONG` heartbeat. A stale or disconnected stream is reported as degraded.

## Normalization

Every normalized market records:

- Gamma market/condition identifiers
- YES and NO CLOB token IDs
- outcome prices
- status, start, close, and venue update timestamps
- liquidity and fee metadata
- source and diagnostics

Every order-book snapshot records full bounded YES/NO bid and ask levels, venue timestamps, source hashes, executable spread, and depth. Research calculations use executable asks and book walking rather than midpoint prices.

## Mispricing Safety

For a binary buy-both-outcomes basket, the engine checks:

- executable YES ask plus executable NO ask
- equal-share depth on both legs
- probability-dependent taker fees
- book-walk slippage and an execution buffer
- data freshness and minimum depth

Only a fully fillable basket below `$1` can be marked tradable in research. A sum above `$1` is monitor-only because short/mint mechanics are not implemented. Linked-market baskets are also research-only until atomic basket execution exists.

## Network And Legal Availability

Do not disable TLS verification to make the provider connect. A hostname mismatch usually indicates DNS interception, an ISP block page, or a proxy problem. Keep the provider degraded, inspect `/api/v1/provider-health/polymarket`, and resolve access through a lawful network path supported in your jurisdiction.

This repository does not bypass regional restrictions. Verify that Polymarket access and trading are permitted where the operator and deployment are located before funding any wallet.

## Read-Only Verification

```bash
curl http://127.0.0.1:3030/api/v1/provider-health/polymarket
curl http://127.0.0.1:3030/api/v1/polymarket/markets
curl -X POST http://127.0.0.1:3030/api/v1/latency-arb/evaluate
curl http://127.0.0.1:3030/api/v1/latency-arb/summary
```

Verify `source`, `book_source`, `reference_fidelity`, `rejection_reasons`, and `paper_only` before interpreting an opportunity.

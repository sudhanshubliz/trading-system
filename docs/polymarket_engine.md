# Polymarket Engine

## Scope

Phase 3 adds a Polymarket research subsystem under `app/polymarket` with:

- provider abstraction
- mock provider for local/dev/test
- real-provider scaffold for later API wiring
- market snapshot persistence
- linked-market validation
- mispricing opportunity generation

## Opportunity Types

- `yes_no_sum_dislocation`
- `linked_market_inconsistency`
- `thin_book_price_gap`
- `cross-market-consistency-monitor`

## Safety

- opportunities are advisory until they pass risk, provider-health, and promotion gates
- stale markets are marked non-tradable
- liquidity and net-edge thresholds are config-driven
- no Polymarket path can silently trigger live execution

## Persistence

- `polymarket_markets`
- `polymarket_market_snapshots`
- `arbitrage_opportunities` with `market="polymarket"`
- `linked_market_validations`

## APIs

- `GET /api/v1/polymarket/markets`
- `GET /api/v1/polymarket/markets/{id}`
- `GET /api/v1/polymarket/opportunities`
- `GET /api/v1/polymarket/opportunities/{id}`
- `GET /api/v1/arbitrage/opportunities`

## Notes

The real provider remains a scaffold. The mock provider is the supported local default until exchange-specific data access, fees, and order-book fidelity are validated.

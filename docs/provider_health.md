# Provider Health

## Scope

Phase 3 adds provider-health tracking under `app/provider_health`.

## Tracked Providers

- Polymarket
- wallet intelligence provider
- event/news provider
- MiroFish adapter
- OpenClaw bridge
- extendable to Binance-side providers later

## States

- `healthy`
- `degraded`
- `unhealthy`

## Persistence

- `provider_health_snapshots`
- `provider_health_events`

## APIs

- `GET /api/v1/provider-health`
- `GET /api/v1/provider-health/{provider_name}`
- `GET /api/v1/provider-health/summary`

## Safety

Provider-health state can veto alpha fusion and block strategy promotion when configured.

# Portfolio Brain

## Scope

Phase 3 adds an explainable allocation layer under `app/portfolio_brain`.

## Inputs

- fused opportunities
- strategy family
- active risk locks
- provider health
- promotion status

## Outputs

- capital by strategy family
- capital by symbol or market
- gross exposure cap
- net exposure guidance
- strategy throttles
- disable recommendations
- watchlist entries

## Persistence

- `portfolio_brain_snapshots`
- `strategy_allocations`

## APIs

- `GET /api/v1/portfolio/brain`
- `GET /api/v1/portfolio/allocations/recommendations`
- `GET /api/v1/portfolio/allocations/history`

## Design Rules

- edge-weighted rather than false-precision optimization
- provider-health-aware
- lock-aware
- promotion-aware
- still advisory; execution remains governed by the existing kernel

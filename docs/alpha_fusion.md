# Alpha Fusion

## Goal

Fuse multiple research inputs into a single explainable candidate opportunity without turning any upstream source into uncontrolled trading truth.

## Phase 3 Inputs

- technical feature snapshot
- regime overlay
- Binance basis/funding
- Binance microstructure
- Polymarket mispricing
- wallet intelligence
- event/news signals
- MiroFish advisory scenarios

## Outputs

- fused score
- recommended direction
- confidence and confidence band
- strategy family
- supporting and veto factors
- source breakdown
- tradable flag
- explanation trail

## Veto Logic

Phase 3 adds veto support for:

- unhealthy providers
- conflicting wallet and event signals
- inherited risk locks through downstream consumers

## Persistence

- `alpha_source_readings`
- `fused_opportunities`
- legacy compatibility through `persisted_fused_alpha`

## APIs

- `GET /api/v1/alpha/sources`
- `GET /api/v1/alpha/fused`
- `GET /api/v1/alpha/fused/{id}`
- `POST /api/v1/alpha/fused`

## Design Rules

- no live side effects
- deterministic, typed scoring
- human-readable explanations
- explicit source attribution
- backward-compatible alpha endpoints

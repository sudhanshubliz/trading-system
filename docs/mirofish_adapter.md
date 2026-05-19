# MiroFish Adapter

## Role

MiroFish remains an optional advisory simulation input.

## Phase 3 Capabilities

- accepts normalized market or event payloads
- generates scenario summaries
- exposes alpha-fusion-compatible source readings
- persists simulation runs
- reports health to the provider-health layer

## Outputs

- expected volatility shift
- expected crowd bias
- scenario confidence
- timestamped advisory run record

## APIs

- `POST /api/v1/simulation/mirofish/run`
- `GET /api/v1/simulation/mirofish/latest`

## Constraint

Simulation output may inform research and overlays, but it must never directly trigger live trades.

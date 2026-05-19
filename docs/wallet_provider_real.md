# Wallet Real Provider

Wallet intelligence keeps the mock provider for local testing and adds a real-provider path for externally sourced wallet activity datasets.

## Design

- abstraction-first provider interface
- duplicate observation suppression
- wallet ID normalization
- stale-data-aware health checks
- provenance and raw-size metadata carried into normalized observations

## Modes

- `WALLET_PROVIDER_MODE=mock`
- `WALLET_PROVIDER_MODE=real`
- `WALLET_PROVIDER_MODE=auto_fallback`

## Output Continuity

The existing wallet profile, observation, scoring, leaderboard, and signal logic is unchanged at the API contract level. The real provider only changes how raw activity is ingested and normalized before those layers run.

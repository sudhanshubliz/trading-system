# Live Ops

The platform remains guarded-live by design, but the operator surface is more production-ready.

## Summary Endpoints

- `GET /api/v1/provider-health/summary`
- `GET /api/v1/system/intelligence/summary`

These summaries now expose:

- unhealthy providers
- recent ingest runs
- backfill degradation
- active locks
- promotion blockers
- allocation throttles
- incident counts

## Safe Deployment Modes

- mock-only local mode
- mixed real/mock mode
- provider-health-aware degraded mode

All of these preserve the existing paper-first and explicit-approval semantics.

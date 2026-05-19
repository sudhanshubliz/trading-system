# Incidents And Operator Workflows

Incident handling is now a first-class operational path.

## Lifecycle

- create
- acknowledge
- resolve
- attach operator notes

## Categories

- `provider_outage`
- `stale_data`
- `execution_anomaly`
- `replay_backfill_failure`
- `risk_lock_persistent`
- `portfolio_allocator_warning`
- `external_dependency_failure`

## API

- `GET /api/v1/system/incidents`
- `GET /api/v1/system/incidents/{id}`
- `POST /api/v1/system/incidents`
- `POST /api/v1/system/incidents/{id}/acknowledge`
- `POST /api/v1/system/incidents/{id}/resolve`
- `GET /api/v1/system/operator-notes`
- `POST /api/v1/system/operator-notes`

OpenClaw remains an orchestration bridge only. It can create alerts and incident records, but it does not bypass the risk engine or become live-trading truth.

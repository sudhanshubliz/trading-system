# OpenClaw Bridge

## Role

OpenClaw is an orchestration adapter, not the execution source of truth.

## Phase 3 Capabilities

- build structured alert payloads
- build approval-request payloads
- persist operator notes
- persist incidents
- expose alert history
- publish health status for provider-health monitoring

## APIs

- `GET /api/v1/system/operator-notes`
- `GET /api/v1/system/incidents`
- `GET /api/v1/system/alerts/history`

## Guardrails

- never bypasses the risk engine
- never silently approves live trading
- dry-run mode is the safe default

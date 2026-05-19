# Backfill Jobs

Backfill jobs provide a persisted, idempotent way to refresh external datasets used by research, replay, and operator workflows.

## Supported Dataset Types

- `polymarket_markets`
- `polymarket_opportunities`
- `wallet_observations`
- `event_observations`

## Behavior

- job IDs are deterministic across dataset, provider, and time range
- rerunning the same job returns the existing completed job unless `force=true`
- job status is persisted as `running`, `completed`, or `failed`
- job payloads carry counts, notes, and error summaries

## API

- `POST /api/v1/research/backfill-jobs`
- `GET /api/v1/research/backfill-jobs`
- `GET /api/v1/research/backfill-jobs/{job_id}`

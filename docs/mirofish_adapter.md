# MiroFish Adapter

## Role

MiroFish is optional, advisory, and non-binding. Its output cannot originate a risk request, approval, or execution. The trading system remains the execution and risk kernel.

MiroFish is a long-running multi-agent scenario simulator, not a low-latency market-data feed. Native simulation creation needs project and graph context and may take substantial time, so the trading system exposes a typed scenario-ingestion boundary instead of coupling the hot path to MiroFish internals.

## Modes

```dotenv
ENABLE_MIROFISH=false
MIROFISH_PROVIDER=mock
MIROFISH_MAX_DATA_AGE_SECONDS=300
MIROFISH_MAX_FUTURE_CLOCK_SKEW_SECONDS=30
MIROFISH_MAX_SCENARIO_CONFIDENCE=0.5
FUSION_WEIGHT_MIROFISH=0.05
```

- Disabled is the production-safe default.
- Mock mode is deterministic, labeled as mock, and capped at low confidence.
- `real` or `external` mode accepts only explicitly ingested, fresh scenario summaries.
- Missing or stale external output produces a neutral degraded response and never blocks the core system.

## External Ingestion

```bash
curl -X POST http://127.0.0.1:3030/api/v1/simulation/mirofish/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "scenario_id":"scenario-2026-07-11-btc",
    "symbol_or_market":"BTCUSDT",
    "simulation_timestamp":"2026-07-11T12:00:00Z",
    "direction_bias":"neutral",
    "expected_crowd_bias":0.1,
    "expected_volatility_shift":0.2,
    "scenario_confidence":0.35,
    "explanation":"Validated external scenario summary",
    "source_run_id":"mirofish-run-123"
  }'
```

Validation enforces timestamp freshness, future clock skew, bounded direction/bias values, required provenance IDs, and a configurable confidence cap. Every accepted record is persisted with `advisory_only=true` and `independent_signal=false`.

## APIs

- `POST /api/v1/simulation/mirofish/run`
- `POST /api/v1/simulation/mirofish/ingest`
- `GET /api/v1/simulation/mirofish/latest`

`/run` returns the latest fresh external scenario in real/external mode. It does not start an uncontrolled remote simulation from the request path.

## Deployment Boundary

Run MiroFish on a private network and authenticate it at the reverse proxy or service-mesh layer. Do not expose an unauthenticated MiroFish instance to the public internet. The adapter intentionally does not accept provider credentials or execute trades.

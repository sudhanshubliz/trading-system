# MiroFish Adapter

## Role

MiroFish is optional, advisory, and non-binding. Its output cannot originate a risk request, approval, or execution. The trading system remains the execution and risk kernel.

MiroFish is a long-running multi-agent scenario simulator, not a low-latency market-data feed. Native simulation creation needs project and graph context and may take substantial time, so the trading system exposes a typed scenario-ingestion boundary instead of coupling the hot path to MiroFish internals.

The supported upstream implementation is [666ghj/MiroFish](https://github.com/666ghj/MiroFish). It runs as a separate AGPL-3.0 service and exposes a Flask API on port `5001`. Keep that deployment operationally separate from this repository.

## Modes

```dotenv
ENABLE_MIROFISH=false
MIROFISH_PROVIDER=mock
MIROFISH_BASE_URL=http://127.0.0.1:5001
MIROFISH_AUTH_TOKEN=
MIROFISH_VERIFY_TLS=true
MIROFISH_MAX_DATA_AGE_SECONDS=300
MIROFISH_MAX_FUTURE_CLOCK_SKEW_SECONDS=30
MIROFISH_MAX_SCENARIO_CONFIDENCE=0.5
FUSION_WEIGHT_MIROFISH=0.05
```

- Disabled is the production-safe default.
- Mock mode is deterministic, labeled as mock, and capped at low confidence.
- `real` or `external` mode accepts only explicitly ingested, fresh scenario summaries.
- External mode can verify a scenario against a completed upstream MiroFish simulation report through `/sync`.
- Missing or stale external output produces a neutral degraded response and never blocks the core system.

## Upstream Deployment

MiroFish requires its own `LLM_API_KEY`, OpenAI-compatible model endpoint, and `ZEP_API_KEY`. Store those only in the separate MiroFish deployment. They are not trading-system credentials and must not be copied into this repository.

The upstream default starts its frontend on `3000`, which conflicts with the operator dashboard. For local integration, start only its backend:

```bash
git clone https://github.com/666ghj/MiroFish.git
cd MiroFish
cp .env.example .env
# Configure MiroFish-owned LLM and Zep credentials in this separate .env.
npm run setup:backend
npm run backend
curl http://127.0.0.1:5001/health
```

Then configure this service:

```dotenv
ENABLE_MIROFISH=true
MIROFISH_PROVIDER=external
MIROFISH_BASE_URL=http://127.0.0.1:5001
MIROFISH_VERIFY_TLS=true
```

The upstream API does not provide native authentication. Keep it on loopback or a private network. If a reverse proxy enforces bearer authentication, set `MIROFISH_AUTH_TOKEN` here.

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

## Verified Remote Sync

`/sync` checks the upstream simulation and requires a completed report before accepting the typed scenario. Numeric fields must come from a reviewed normalization process; the adapter deliberately does not parse free-form report prose into direction or confidence.

```bash
curl -X POST http://127.0.0.1:3030/api/v1/simulation/mirofish/sync \
  -H 'Content-Type: application/json' \
  -d '{
    "simulation_id":"sim_example",
    "scenario_id":"scenario-example-btc",
    "symbol_or_market":"BTCUSDT",
    "simulation_timestamp":"2026-07-11T18:00:00Z",
    "direction_bias":"neutral",
    "expected_crowd_bias":0.0,
    "expected_volatility_shift":0.2,
    "scenario_confidence":0.3,
    "explanation":"Operator-reviewed structured summary"
  }'
```

The persisted provenance includes upstream simulation/report IDs and explicitly records `report_text_used_as_signal=false`.

## APIs

- `POST /api/v1/simulation/mirofish/run`
- `POST /api/v1/simulation/mirofish/ingest`
- `POST /api/v1/simulation/mirofish/sync`
- `GET /api/v1/simulation/mirofish/health`
- `GET /api/v1/simulation/mirofish/latest`

`/run` returns the latest fresh external scenario in real/external mode. It does not start an uncontrolled remote simulation from the request path.

## Deployment Boundary

Run MiroFish on a private network and authenticate it at the reverse proxy or service-mesh layer. Do not expose an unauthenticated MiroFish instance to the public internet. The adapter intentionally does not accept trading credentials or execute trades.

MiroFish outputs remain advisory even when upstream health is green. StrategyOwner marks this family non-tradable, and unavailable/stale output resolves to a neutral zero-confidence scenario.

# trading-system

FastAPI backend for a safe-by-default trading platform with a live-protected execution kernel plus Phase 1, Phase 2, and Phase 3 extensions for Binance alpha, prediction-market research, multi-source fusion, provider-aware safety gating, and promotion-aware portfolio recommendations.

The remaining production-hardening scope is now implemented as well: real/mock/auto-fallback provider wiring for Polymarket, wallet intelligence, and event/news feeds; persisted backfill jobs; higher-fidelity prediction-market replay metadata; correlation-aware portfolio throttles; richer incident workflows; and more operator-friendly live-ops summaries.

## What This Repo Is Now

The platform is organized as a research-to-execution stack:

- `app/market_data`, `app/signals`, `app/risk`, `app/execution`, `app/live`, `app/portfolio`
  - Existing Binance ingestion, signal evaluation, approvals, paper/shadow/live execution, rollout controls, capital scaling, and portfolio orchestration.
- `app/features/tradingview_like`
  - TradingView-style feature extraction in Python. Indicators are features, not standalone trade decisions.
- `app/regime`
  - Regime classification for `trending_up`, `trending_down`, `mean_reverting`, `volatile_chop`, `compressed_breakout_setup`, and `risk_off`.
- `app/alpha_fusion`
  - Normalized alpha-source readings plus explainable fused opportunities.
- `app/research`
  - Experiment, run, and artifact persistence for research and dashboard workflows.
- `app/arbitrage`
  - Phase 2 Binance basis/funding opportunity detection, persistence, tradability checks, and alpha-source emission.
- `app/features/microstructure`
  - Phase 2 Binance order-book and trade-flow feature extraction with short-horizon microstructure policies.
- `app/execution_quality`
  - Phase 2 execution-quality records and scoring for paper, shadow, replay, and guarded live paths.
- `app/polymarket`
  - Phase 3 Polymarket provider abstraction, market snapshots, linked-market validation, and mispricing opportunity generation.
- `app/wallet_intel`
  - Phase 3 wallet profile scoring, observations, leaderboards, and wallet-driven signals through mock or real-provider scaffolds.
- `app/event_signals`
  - Phase 3 normalized event/news framework with timeliness decay, event windows, and structured event signals.
- `app/provider_health`
  - Phase 3 provider health snapshots, degradation tracking, and veto hooks for fusion and promotion.
- `app/portfolio_brain`
  - Phase 3 explainable allocation recommendations driven by fused opportunities, locks, promotion status, and provider health.
- `app/promotion`
  - Phase 3 strategy stage tracking and review logic for research to paper to shadow to guarded live promotion.
- `app/agents`
  - Phase 3 OpenClaw orchestration bridge for alerts, approvals, operator notes, and incident logging.
- `app/simulation`
  - Phase 3 MiroFish advisory simulation adapter for optional scenario overlays.

## Safe Startup Flow

The default runtime remains safe:

- `ENABLE_LIVE_TRADING=false`
- `LIVE_TRADING_ARMED=false`
- paper execution remains the default mode
- shadow mode remains isolated
- live execution still requires the existing guarded controller, approvals, locks, and rollout policy
- new intelligence services only generate research, simulated fills, allocation guidance, and candidate opportunities; they do not silently place live orders

Start locally:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
uvicorn app.main:app --reload
```

## Phase 1, Phase 2, And Phase 3 Additions

Phase 1 foundation is implemented and persisted:

- TradingView-like feature registry and feature computation
  - EMA, SMA, RSI, MACD, ATR, VWAP
  - Donchian, Bollinger, Keltner squeeze
  - breakout/range compression
  - simple market structure
  - order-block / FVG research placeholders
- regime engine
- explainable alpha-source readings
- fused opportunity persistence
- research experiment/run/artifact persistence
- Alembic migration support for the new platform tables
- dashboard-ready APIs for features, alpha sources/fused opportunities, regimes, research, and system intelligence summary

Phase 2 extends the crypto core with:

- Binance basis/funding engine
  - spot vs perp basis approximation
  - funding extreme detection
  - z-score and tradability checks
  - persisted basis/funding opportunities under `arbitrage_opportunities`
- Binance microstructure engine
  - top-of-book spread
  - top-level and top-N imbalance
  - microprice
  - order-book pressure
  - trade-flow imbalance
  - burst / volatility / stale-book states
  - persisted snapshots under `microstructure_feature_snapshots`
- execution-quality tracking
  - slippage, latency, partial-fill, and spread-aware scoring
  - records for paper, shadow, replay, and live execution paths
- stronger risk locks
  - stale data
  - liquidity thin
  - volatility shock
  - execution anomaly
  - basis-data integrity
- replay integration
  - deterministic synthetic order-book, tape, and funding approximations from replay candles
  - persisted replay runs now carry Phase 2 artifacts and fidelity notes

Phase 3 expands the platform into a multi-source intelligence layer with:

- Polymarket mispricing engine
  - mock plus real-provider scaffolds
  - market snapshots, order-book snapshots, linked-market validation
  - yes/no sum dislocation detection, thin-book gap monitoring, linked-market inconsistency checks
- wallet intelligence
  - mock provider plus real-provider scaffold
  - wallet profiles, observations, signals, and leaderboards
  - follow, fade, ignore, and monitor-only actions
- event/news framework
  - normalized events, headlines, and macro-style calendars
  - pre-event, during-event, post-event, and stale-event handling
  - importance and timeliness-aware event signals
- alpha fusion expansion
  - multi-source weighting for Polymarket, wallet, event, and MiroFish signals
  - provider-health veto support and source attribution
- portfolio brain
  - strategy and market allocation recommendations
  - lock-aware and provider-aware throttling
- promotion ladder
  - strategy status persistence and promotion reviews
- provider health
  - provider snapshots and degradation summaries
- OpenClaw bridge
  - dry-run-safe alerts, approval payloads, operator notes, and incidents
- MiroFish adapter
  - advisory scenario summaries and fusion-compatible scenario signals

Production hardening beyond the Phase 3 scaffold now adds:

- real provider wiring with safe fallback
  - `mock`, `real`, and `auto_fallback` modes for Polymarket, wallet intelligence, and event/news providers
  - provider-health-aware degradation instead of brittle hard failure in local or mixed environments
- stronger replay and backfill workflows
  - replay fidelity modes with persisted fidelity metadata
  - external snapshot and annotation support for prediction-market, wallet, and event replay inputs
  - persisted backfill jobs for Polymarket, wallet, and event datasets
- portfolio correlation and live-ops polish
  - bucketed correlation throttles for crypto directional, event-market, and wallet-follow risk
  - incident lifecycle support for create, acknowledge, resolve, notes, and structured alert history
  - system summaries that surface unhealthy providers, backfill degradation, promotion blockers, and allocation throttles

## Strategy Families

The target platform supports a portfolio of small risk-controlled edges rather than one god strategy:

- Binance microstructure
- Binance basis / funding dislocations
- Polymarket mispricing and linked-market consistency
- wallet intelligence
- event / news signals
- technical feature + regime overlays

The platform now covers the technical feature stack, regime, fusion, Binance basis/funding, Binance microstructure, execution-quality scoring, Polymarket mispricing, wallet intelligence, event/news signals, provider health, promotion reviews, and portfolio-brain recommendations, while still preserving the existing execution kernel.

## Research To Live Ladder

The repo is structured for staged promotion:

1. Research only
2. Paper
3. Shadow
4. Limited live
5. Scaled live
6. Institutional-style ops

Phase 3 keeps the same paper/shadow/live safety gates and adds broader intelligence, orchestration, and allocation services without changing the default guarded-live semantics.

## Key APIs

Existing alpha APIs remain available:

- `GET /api/v1/alpha/features/{symbol}`
- `GET /api/v1/alpha/fused`
- `POST /api/v1/alpha/fused`

New Phase 1 dashboard APIs:

- `GET /api/v1/features/catalog`
- `POST /api/v1/features/compute`
- `POST /api/v1/features/compute/batch`
- `GET /api/v1/alpha/sources`
- `GET /api/v1/alpha/fused/{id}`
- `GET /api/v1/regime/current`
- `GET /api/v1/regime/history`
- `GET /api/v1/research/experiments`
- `GET /api/v1/research/experiments/{id}`
- `GET /api/v1/research/runs`
- `GET /api/v1/research/runs/{id}`
- `GET /api/v1/system/intelligence/summary`

New and extended Phase 2 APIs:

- `GET /api/v1/arbitrage/opportunities`
- `GET /api/v1/arbitrage/opportunities/{id}`
- `GET /api/v1/microstructure/current`
- `GET /api/v1/microstructure/history`
- `GET /api/v1/execution/quality`
- `GET /api/v1/execution/quality/{trade_id}`
- `GET /api/v1/risk/locks/current`
- `GET /api/v1/risk/locks/history`
- `GET /api/v1/alpha/sources?source=binance_microstructure`
- `GET /api/v1/alpha/sources?source=basis_funding`

New Phase 3 APIs:

- `GET /api/v1/polymarket/markets`
- `GET /api/v1/polymarket/markets/{id}`
- `GET /api/v1/polymarket/opportunities`
- `GET /api/v1/polymarket/opportunities/{id}`
- `GET /api/v1/wallets`
- `GET /api/v1/wallets/{wallet_id}`
- `GET /api/v1/wallets/leaderboard`
- `GET /api/v1/wallets/signals`
- `GET /api/v1/wallets/observations`
- `GET /api/v1/events`
- `GET /api/v1/events/{event_id}`
- `GET /api/v1/events/signals`
- `GET /api/v1/events/providers/health`
- `GET /api/v1/provider-health`
- `GET /api/v1/provider-health/{provider_name}`
- `GET /api/v1/provider-health/summary`
- `GET /api/v1/portfolio/brain`
- `GET /api/v1/portfolio/allocations/recommendations`
- `GET /api/v1/portfolio/allocations/history`
- `GET /api/v1/promotion/status`
- `POST /api/v1/promotion/review`
- `GET /api/v1/promotion/ladder`
- `GET /api/v1/system/operator-notes`
- `POST /api/v1/system/operator-notes`
- `GET /api/v1/system/incidents`
- `GET /api/v1/system/incidents/{id}`
- `POST /api/v1/system/incidents`
- `POST /api/v1/system/incidents/{id}/acknowledge`
- `POST /api/v1/system/incidents/{id}/resolve`
- `GET /api/v1/system/alerts/history`
- `POST /api/v1/simulation/mirofish/run`
- `GET /api/v1/simulation/mirofish/latest`
- `POST /api/v1/research/backfill-jobs`
- `GET /api/v1/research/backfill-jobs`
- `GET /api/v1/research/backfill-jobs/{job_id}`

Example calls:

```bash
curl http://127.0.0.1:8000/api/v1/features/catalog

curl -X POST http://127.0.0.1:8000/api/v1/features/compute \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT"}'

curl -X POST http://127.0.0.1:8000/api/v1/alpha/fused \
  -H "Content-Type: application/json" \
  -d '{"symbols":["BTCUSDT","ETHUSDT"]}'

curl "http://127.0.0.1:8000/api/v1/alpha/sources?symbol=BTCUSDT"

curl "http://127.0.0.1:8000/api/v1/regime/current?symbol=BTCUSDT"

curl "http://127.0.0.1:8000/api/v1/arbitrage/opportunities?symbol=BTCUSDT&tradable=true"

curl "http://127.0.0.1:8000/api/v1/microstructure/current?symbol=BTCUSDT"

curl "http://127.0.0.1:8000/api/v1/execution/quality?symbol=BTCUSDT&mode=paper"

curl "http://127.0.0.1:8000/api/v1/risk/locks/current"

curl http://127.0.0.1:8000/api/v1/system/intelligence/summary

curl http://127.0.0.1:8000/api/v1/polymarket/opportunities

curl http://127.0.0.1:8000/api/v1/wallets/leaderboard

curl http://127.0.0.1:8000/api/v1/events/signals

curl http://127.0.0.1:8000/api/v1/provider-health/summary

curl -X POST http://127.0.0.1:8000/api/v1/research/backfill-jobs \
  -H "Content-Type: application/json" \
  -d '{"dataset_type":"polymarket_markets","provider_name":"polymarket"}'

curl -X POST http://127.0.0.1:8000/api/v1/alpha/fused \
  -H "Content-Type: application/json" \
  -d '{"targets":["pm_crypto_etf_approval"]}'

curl http://127.0.0.1:8000/api/v1/portfolio/brain

curl -X POST "http://127.0.0.1:8000/api/v1/promotion/review?strategy_name=prediction_market_phase3"

curl -X POST http://127.0.0.1:8000/api/v1/simulation/mirofish/run \
  -H "Content-Type: application/json" \
  -d '{"symbol_or_market":"pm_crypto_etf_approval","payload":{"event_bias":0.4,"polymarket_bias":0.5}}'

curl -X POST http://127.0.0.1:8000/api/v1/system/incidents \
  -H "Content-Type: application/json" \
  -d '{"category":"provider_outage","severity":"high","source":"operator","impacted_scope":"provider","title":"Wallet provider unhealthy","related_provider":"wallet_intel"}'
```

## Persistence And Migrations

The repo now includes Alembic for the persistence database.

Run the migration:

```bash
alembic upgrade head
```

New persisted tables include:

- `feature_runs`
- `alpha_source_readings`
- `fused_opportunities`
- `regime_snapshots`
- `research_experiments`
- `experiment_runs`
- `experiment_artifacts`
- `microstructure_feature_snapshots`

Phase 2 and roadmap tables:

- `wallet_profiles`, `wallet_observations`, `wallet_signals`
- `arbitrage_opportunities`
- `event_observations`, `event_signals`
- `strategy_allocations`
- `promotion_reviews`
- `execution_quality_records`
- `provider_health_events`
- `risk_lock_events`
- `operator_notes`
- `incident_records`

Phase 3 tables:

- `polymarket_markets`
- `polymarket_market_snapshots`
- `linked_market_validations`
- `provider_health_snapshots`
- `provider_ingest_runs`
- `strategy_promotion_status`
- `alert_history`
- `portfolio_brain_snapshots`
- `mirofish_simulation_runs`
- `backfill_jobs`
- `replay_fidelity_metadata`

## Configuration

`.env.example` now includes grouped settings for:

- feature engine controls
- fusion weights
- regime thresholds
- research and promotion thresholds
- Binance microstructure and basis/funding controls
- execution simulation knobs
- Polymarket, wallet, and event providers
- provider modes, timeouts, and real/mock fallback controls
- Phase 3 alpha fusion weights and health vetoes
- provider health
- portfolio brain allocation limits
- replay fidelity and external partial-data controls
- backfill batch, retry, and resume controls
- portfolio correlation bucket caps
- incident auto-escalation controls
- promotion ladder thresholds
- OpenClaw bridge
- MiroFish adapter

Important safe defaults:

- `ENABLE_LIVE_TRADING=false`
- `ENABLE_BASIS_FUNDING_ENGINE=true`
- `ENABLE_MICROSTRUCTURE_ENGINE=true`
- `ENABLE_POLYMARKET_ENGINE=true`
- `ENABLE_WALLET_INTEL=true`
- `ENABLE_EVENT_SIGNALS=true`
- `EXECUTION_QUALITY_ENABLED=true`
- `OPENCLAW_DRY_RUN=true`
- `ENABLE_MIROFISH=false`
- all Phase 2 risk locks enabled

These settings still only affect analysis, paper, shadow, replay, and guarded approvals unless live trading is explicitly enabled and armed.

## Mock vs Real Providers

Provider integrations are built with safe local defaults:

- `POLYMARKET_PROVIDER_MODE=mock`
- `WALLET_PROVIDER_MODE=mock`
- `EVENT_PROVIDER_MODE=mock`
- `MIROFISH_PROVIDER=mock`

Use `auto_fallback` when you want the real provider first but still need a safe local/dev escape hatch. Legacy aliases like `POLYMARKET_PROVIDER`, `WALLET_PROVIDER`, and `EVENT_PROVIDER` are still accepted for backward compatibility, but `*_PROVIDER_MODE` is now the preferred config surface.

## Replay Fidelity

Replay remains honest about fidelity:

- Basis/funding replay uses candle-derived spot-vs-perp approximations when native historical funding snapshots are not available.
- Microstructure replay builds deterministic synthetic order-book and trade-flow views from candle paths and volume.
- Execution-quality replay scores simulated fills against replay snapshots rather than exchange-confirmed venue latency.
- Prediction-market replay is best-effort and snapshot-based when stored Polymarket or event data is available.
- Wallet and event replay are driven by stored observations/signals rather than claims of perfect historical discovery timing.
- Fidelity metadata is persisted per replay run so the UI and reviews can see exactly what external data was and was not available.

## Backfill Jobs

Use `/api/v1/research/backfill-jobs` to seed or refresh Polymarket, wallet, and event datasets in a resumable, idempotent way. Re-running the same dataset/provider/time-range combination returns the same job unless `force=true` is supplied.

## Live Ops

`/api/v1/system/intelligence/summary` now surfaces:

- unhealthy providers
- active risk locks
- recent backfill state
- promotion blockers
- allocation throttles
- incident counts

This keeps the platform aligned with the guarded-live design: operators see why the system is throttling or vetoing before any live path is considered.

## Local And Docker

Run locally:

```bash
uvicorn app.main:app --reload
```

Run with Docker:

```bash
docker build -f deploy/Dockerfile -t trading-system .
docker run --rm -p 8000:8000 --env-file .env trading-system
```

Or with compose:

```bash
docker compose -f deploy/docker-compose.yml up --build
```

## Tests

Run everything:

```bash
pytest
```

Run the Phase 1 suite only:

```bash
pytest tests/test_alpha_fusion.py tests/test_phase1_platform_intelligence.py tests/test_alembic_migration_smoke.py
```

Run the Phase 2 suite only:

```bash
pytest tests/test_phase2_crypto_core.py tests/test_replay_engine.py tests/test_alembic_migration_smoke.py
```

Run the Phase 3 suite only:

```bash
pytest tests/test_phase3_intelligence_platform.py tests/test_alembic_migration_smoke.py
```

Run the remaining hardening suite only:

```bash
pytest tests/test_remaining_hardening.py tests/test_alembic_migration_smoke.py
```

## Docs

- [Architecture](docs/architecture.md)
- [Feature Engine](docs/feature_engine.md)
- [Alpha Fusion](docs/alpha_fusion.md)
- [Binance Basis Funding](docs/binance_basis_funding.md)
- [Microstructure Engine](docs/microstructure_engine.md)
- [Execution Quality](docs/execution_quality.md)
- [Polymarket Engine](docs/polymarket_engine.md)
- [Polymarket Real Provider](docs/polymarket_provider_real.md)
- [Wallet Intelligence](docs/wallet_intelligence.md)
- [Wallet Real Provider](docs/wallet_provider_real.md)
- [Event Signals](docs/event_signals.md)
- [Event Real Provider](docs/event_provider_real.md)
- [Risk Model](docs/risk_model.md)
- [Risk Locks](docs/risk_locks.md)
- [Replay Fidelity](docs/replay_fidelity.md)
- [Prediction Market Replay](docs/prediction_market_replay.md)
- [Portfolio Brain](docs/portfolio_brain.md)
- [Portfolio Correlation](docs/portfolio_correlation.md)
- [Promotion Ladder](docs/promotion_ladder.md)
- [Provider Health](docs/provider_health.md)
- [Provider Interfaces](docs/provider_interfaces.md)
- [OpenClaw Bridge](docs/openclaw_bridge.md)
- [Backfill Jobs](docs/backfill_jobs.md)
- [Incidents And Operator Workflows](docs/incidents_and_operator_workflows.md)
- [Live Ops](docs/live_ops.md)
- [MiroFish Adapter](docs/mirofish_adapter.md)

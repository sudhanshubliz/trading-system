# trading-system

Minimal FastAPI backend for a trading system with paper, shadow, and tightly guarded live execution paths. Milestone 12 adds advanced analytics, portfolio management, and multi-strategy orchestration on top of the Milestone 11 live rollout policy, capital scaling guardrails, staged phase gating, and automatic rollback controls.

## Overview

This project is a backend-first trading platform for experimenting with market-data ingestion, signal generation, risk checks, paper trading, shadow execution, and guarded live-trading workflows.

Core capabilities:

- Binance REST and WebSocket market-data ingestion
- Signal evaluation, approvals, and execution tracking
- Paper trading, shadow mode, and guarded live execution controls
- Rollout phases, capital scaling, and rollback protection
- Portfolio allocation, rebalancing, and multi-strategy orchestration
- Replay, optimization, reporting, analytics, and ops recovery endpoints

## Requirements

- macOS with Python 3.12+
- Internet access for live Binance market data
- SQLite, included with Python on macOS

## Quick Start

### 1. Clone and enter the project

```bash
cd trading-system
```

### 2. Create a virtual environment and install dependencies

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 3. Create your local environment file

```bash
cp .env.example .env
```

Important setup notes:

- Keep `ENABLE_LIVE_TRADING=false` unless you are explicitly testing guarded live workflows.
- Leave `TELEGRAM_SIMULATION_MODE=true` for local development unless you are wiring a real Telegram runtime.
- The default SQLite files are created locally from `DATABASE_URL` and `PERSISTENCE_DB_URL`.

### 4. Run the API

```bash
uvicorn app.main:app --reload
```

The service starts on `http://127.0.0.1:8000` by default.

### 5. Run the test suite

```bash
pytest
```

## Configuration

Primary runtime settings live in [.env.example](/Users/sudhanshu_thakur/Documents/workspace/binance/trading-system/.env.example). The most important groups are:

- market data and Binance endpoints
- signal-generation thresholds and indicator lookbacks
- paper-trading and execution controls
- persistence and reporting settings
- live-trading guardrails and rollout policy
- portfolio and analytics configuration

## Endpoints

- `GET /api/v1/health`
- `GET /api/v1/health/livez`
- `GET /api/v1/health/readyz`
- `GET /api/v1/market-data/health`
- `GET /api/v1/market-data/snapshots`
- `GET /api/v1/market-data/snapshots/{symbol}`
- `GET /api/v1/market-data/candles/{symbol}/{timeframe}`
- `GET /api/v1/signals`
- `GET /api/v1/signals/{signal_id}`
- `POST /api/v1/signals/evaluate`
- `GET /api/v1/risk/summary`
- `POST /api/v1/risk/validate`
- `POST /api/v1/risk/evaluate-signals`
- `GET /api/v1/approvals`
- `GET /api/v1/approvals/pending`
- `POST /api/v1/approvals/from-assessment/{id}`
- `POST /api/v1/approvals/{id}/approve`
- `POST /api/v1/approvals/{id}/reject`
- `GET /api/v1/positions`
- `GET /api/v1/positions/{id}`
- `GET /api/v1/trades`
- `GET /api/v1/trades/{id}`
- `GET /api/v1/pnl`
- `POST /api/v1/control/pause`
- `POST /api/v1/control/resume`
- `GET /api/v1/control/status`
- `POST /api/v1/replay/run`
- `GET /api/v1/replay/runs`
- `GET /api/v1/replay/runs/{run_id}`
- `GET /api/v1/replay/runs/{run_id}/metrics`
- `POST /api/v1/optimization/run`
- `GET /api/v1/optimization/runs`
- `GET /api/v1/optimization/runs/{run_id}`
- `GET /api/v1/optimization/runs/{run_id}/leaderboard`
- `GET /api/v1/reports/daily`
- `GET /api/v1/reports/weekly`
- `GET /api/v1/reports/strategy`
- `GET /api/v1/reports/symbol`
- `POST /api/v1/shadow/start`
- `POST /api/v1/shadow/stop`
- `GET /api/v1/shadow/status`
- `GET /api/v1/live/status`
- `POST /api/v1/live/arm`
- `POST /api/v1/live/disarm`
- `GET /api/v1/live/locks`
- `POST /api/v1/live/locks/{lock_id}/clear`
- `POST /api/v1/live/execute/{assessment_id}`
- `POST /api/v1/live/reconcile`
- `GET /api/v1/rollout/status`
- `POST /api/v1/rollout/phase/{phase}`
- `POST /api/v1/rollout/scale-up`
- `POST /api/v1/rollout/scale-down`
- `POST /api/v1/rollout/rollback`
- `GET /api/v1/rollout/history`
- `GET /api/v1/rollout/capital`
- `GET /api/v1/portfolio/status`
- `GET /api/v1/portfolio/allocations`
- `POST /api/v1/portfolio/evaluate`
- `POST /api/v1/portfolio/rebalance`
- `GET /api/v1/portfolio/history`
- `GET /api/v1/analytics/portfolio`
- `GET /api/v1/analytics/strategy`
- `GET /api/v1/analytics/symbol`
- `GET /api/v1/analytics/regime`
- `GET /api/v1/analytics/attribution`
- `GET /api/v1/ops/status`
- `GET /api/v1/ops/incidents`
- `POST /api/v1/ops/recover`

## Operational Notes

- Live trading is disabled by default and must be explicitly enabled with both `ENABLE_LIVE_TRADING=true` and `LIVE_TRADING_ARMED=true` runtime arming flow before any live order path can proceed.
- Live rollout policy is an additional mandatory gate for live execution. Live orders are blocked unless the rollout phase is not `disabled`, rollout capital guardrails allow the order, and Milestone 9 hard locks and approvals also pass.
- Portfolio orchestration is an additional mandatory gate before execution. Candidate ranking, allocation, and portfolio guardrails must pass before live execution can proceed, and this layer does not replace hard locks, rollout policy, or approval checks.
- Paper and shadow modes continue to work independently of live mode and remain isolated by `execution_mode`.
- Replay and optimization continue to use replay-local isolated services and never mutate live paper state.
- Critical runtime state is durably persisted in SQLite:
  - signals
  - risk assessments
  - approvals
  - trades
  - positions
  - replay runs
  - optimization runs
  - reports
  - event store
  - live locks
- Startup is restart-safe:
  - open positions are recovered
  - pending and executed approvals are recovered
  - historical trades remain queryable after restart
  - live arm/disarm state is restored safely
  - active live locks remain active until cleared or resolved
  - startup preflight results are exposed via readiness and ops status
  - manual and startup recovery runs are written to the event store
- Reports are generated from persisted state only and expose zero-safe outputs when no data exists.
- Shadow mode reuses live market data, signal, and risk evaluation while persisting isolated `execution_mode="shadow"` trades and approvals.
- Shadow mode can be started and stopped without affecting normal paper mode.
- Market-data staleness can block new paper and shadow executions when `STALE_MARKET_DATA_BLOCKS_TRADING=true`.
- `GLOBAL_PAUSE` and the runtime control endpoints block new executions while keeping reads and reporting available.
- Live execution is controller-only. Routes and services never call Binance directly; the `LiveController` enforces guardrails, approval checks, and hard locks first.
- Rollout phases are explicit and persisted:
  - `disabled`: no live orders
  - `micro`: initial low-capital rollout
  - `limited`: moderate staged rollout
  - `scaled`: full configured live rollout cap
- Capital scaling and rollback guardrails are persisted and auditable:
  - total live capital capped by `LIVE_MAX_CAPITAL_TOTAL`
  - initial phase cap set by `LIVE_INITIAL_CAPITAL_LIMIT`
  - scale-up requires minimum live trade count, win rate, profit factor, and drawdown/loss thresholds
  - strategy capital capped by `LIVE_STRATEGY_MAX_CAPITAL_PCT`
  - symbol capital capped by `LIVE_SYMBOL_MAX_CAPITAL_PCT`
  - portfolio concentration capped by `LIVE_PORTFOLIO_MAX_CORRELATED_POSITIONS`
  - auto de-escalation can reduce `scaled -> limited -> micro -> disabled`
  - critical rollback can auto-disarm live trading when `LIVE_AUTO_DISARM_ON_CRITICAL_ROLLBACK=true`
- Portfolio allocation and orchestration are explicit and auditable:
  - allocator enforces total capital, reserve cash, single-trade, per-strategy, per-symbol, and simple correlation-cluster caps
  - candidate ranking is deterministic and combines score, reward:risk, diversification value, and current exposure
  - conflicting same-symbol opposite-side candidates are rejected or deferred
  - orchestration decisions, denials, and rebalance plans are written to persistence
- Advanced analytics are persistence-backed and zero-safe:
  - portfolio metrics summarize total pnl, win rate, expectancy, and drawdown
  - attribution is available by strategy and symbol
  - execution mode splits expose paper / shadow / live contribution
  - regime tagging classifies recent performance into `trending`, `ranging`, `high-vol`, or `low-vol`
- Hard live locks can block or halt live execution automatically:
  - `GLOBAL_PAUSE`
  - `MARKET_DATA_STALE`
  - `DAILY_LOSS_LIMIT`
  - `WEEKLY_LOSS_LIMIT`
  - `CONSECUTIVE_LOSS_LIMIT`
  - `OPEN_RISK_LIMIT`
  - `OPEN_POSITION_LIMIT`
  - `EXCHANGE_SYNC_ERROR`
  - `MANUAL_LIVE_DISARM`
  - `LIVE_NOT_ARMED`
  - `APPROVAL_REQUIRED`
  - `ORDER_VALIDATION_FAILED`
- Live reconciliation compares persisted live trades and positions against exchange open orders and exchange positions. Critical mismatches activate `EXCHANGE_SYNC_ERROR` and persist audit events.

## Telegram Control Plane

The Telegram runtime path is transport-optional and safe for tests. Supported control commands:

- `/positions`
- `/pnl`
- `/risk`
- `/start_shadow`
- `/stop_shadow`
- `/pause`
- `/resume`
- `/approve <approval_id|trade_id>`
- `/reject <approval_id|trade_id>`
- `/live_status`
- `/arm_live`
- `/disarm_live`
- `/locks`
- `/incidents`
- `/recover`
- `/clear_lock <lock_id>`
- `/rollout_status`
- `/set_rollout_phase <disabled|micro|limited|scaled>`
- `/scale_up`
- `/scale_down`
- `/rollback_live`
- `/capital_status`
- `/portfolio_status`
- `/allocations`
- `/strategy_stats`
- `/symbol_stats`
- `/rebalance`
- `/regime_status`

Trade alerts and approval formatting include:

- entry
- stop-loss
- target
- risk context
- confidence

Dangerous operator commands use explicit confirmation text when `TELEGRAM_CONFIRM_DANGEROUS_ACTIONS=true`:

- `/arm_live` -> `CONFIRM_ARM`
- `/disarm_live` -> `CONFIRM_DISARM`
- `/clear_lock <lock_id>` -> `CONFIRM_CLEAR_LOCK <lock_id>`
- `/set_rollout_phase <phase>` -> `CONFIRM_SET_ROLLOUT_PHASE <phase>`
- `/scale_up` -> `CONFIRM_SCALE_UP`
- `/scale_down` -> `CONFIRM_SCALE_DOWN`
- `/rollback_live` -> `CONFIRM_ROLLBACK_LIVE`
- `/resume` -> `CONFIRM_RESUME`

## Persistence And Reporting

- Persistence uses a dedicated SQLite database configured via `PERSISTENCE_DB_URL`.
- Repository writes sanitize non-finite numbers and store machine-readable payloads for auditability.
- Major actions are logged and appended to the event store:
  - signal generation
  - risk pass / reject
  - approval receipt
  - trade creation / execution / close
  - stop-loss / take-profit events
  - shadow execution events
  - live order requested / submitted / rejected
  - live fill and reconciliation mismatch events
  - live lock activation / clearance
- Portfolio and analytics persistence extends auditability with:
  - portfolio snapshots
  - allocation and orchestration decisions
  - candidate denial reasons
  - rebalance plans
  - analytics and attribution reports
- Reporting metrics include:
  - total trades
  - win rate
  - net pnl
  - expectancy
  - max drawdown
  - profit factor
  - average hold time
  - risk per trade
  - equity curve
  - drawdown timeline

## Live Trading Safety

- Live trading requires explicit environment configuration:
  - `ENABLE_LIVE_TRADING=true`
  - valid `BINANCE_API_KEY` and `BINANCE_API_SECRET`
  - optional runtime arming via `POST /api/v1/live/arm` or `/arm_live`
- `LIVE_TRADING_ARMED=false` remains the safe startup default.
- Live execution only proceeds when:
  - live trading is enabled
  - runtime arm state is true
  - no hard live locks are active
  - global pause is not active
  - persisted risk assessment exists and is `approved_for_review`
  - explicit approval exists when required
  - rollout policy allows the trade
  - portfolio orchestration allows the trade and sizing
  - market data is fresh
  - order validation passes
- Tests never place real Binance orders. They use fake or stub adapters only.

## Operator UX And Recovery

- `/api/v1/ops/status` returns an operator-facing summary for live arm state, active locks, pause state, market data freshness, exchange and reconciliation health, open live positions, pending approvals, and recent startup or recovery warnings.
- `/api/v1/ops/incidents` returns alert-friendly recent incidents built from active locks and critical audit events.
- `/api/v1/ops/recover` runs a safe manual recovery routine that rebuilds in-memory execution indexes from persistence, reloads active locks, reconciles live control state, and optionally attempts live reconciliation when configured.
- `/api/v1/rollout/status` and `/api/v1/rollout/capital` expose current rollout phase, deployed capital, remaining headroom, and strategy/symbol allocations for alerting and operator review.
- `/api/v1/rollout/history` exposes persisted rollout phase history.
- `/api/v1/rollout/phase/{phase}`, `/api/v1/rollout/scale-up`, `/api/v1/rollout/scale-down`, and `/api/v1/rollout/rollback` provide explicit rollout controls with persisted audit events.
- `/api/v1/portfolio/status`, `/api/v1/portfolio/allocations`, and `/api/v1/portfolio/history` expose deployed capital, free capital, allocation state, orchestration denials, and portfolio audit records.
- `/api/v1/portfolio/evaluate` evaluates multiple approved candidates under portfolio constraints and returns deterministic ranking and sizing decisions.
- `/api/v1/portfolio/rebalance` returns a structured rebalance plan when strategy or symbol exposures exceed configured caps.
- `/api/v1/analytics/portfolio`, `/api/v1/analytics/strategy`, `/api/v1/analytics/symbol`, `/api/v1/analytics/regime`, and `/api/v1/analytics/attribution` expose advanced analytics, attribution, and regime summaries from persistence-backed trade history.
- `scripts/preflight_check.py` runs startup checks and prints a structured report without requiring external services in tests.
- `scripts/run_migrations_or_bootstrap.py` safely initializes core and persistence tables.

## Deployment

Example deployment assets live in [`deploy/`](/Users/sudhanshu_thakur/Documents/workspace/binance/trading-system/deploy):

- `Dockerfile` includes a container `HEALTHCHECK` against `/api/v1/health/livez`
- `docker-compose.yml` mounts persistent SQLite storage, sets a restart policy, and health-checks `/api/v1/health/readyz`
- Kubernetes example manifests include liveness, readiness, and startup probes

These files are safe-default examples only:

- live trading still requires explicit environment flags and runtime arming
- no production secrets are committed
- tests still make no real exchange or Telegram network calls

## Test

```bash
cd trading-system
pytest
```

# Current System Audit

Generated on 2026-05-19 for the existing `trading-system` repo. This audit reflects the codebase as implemented before the new strategy-owner layer was added, with notes on what is already production-oriented versus still paper/research-scaffolded.

## 1. Existing Module Map

### Core application
- `app/main.py`: FastAPI bootstrap
- `app/core/lifecycle.py`: startup wiring for nearly all services
- `app/config/settings.py`: environment-driven configuration

### Market / strategy / research stack
- `app/market_data/`: Binance spot/futures REST + WebSocket ingestion, caches, schemas, types
- `app/signals/`: core crypto signal engine
- `app/features/`: TradingView-like feature engine
- `app/regime/`: regime classification
- `app/alpha_fusion/`: multi-source alpha aggregation
- `app/arbitrage/`: basis / funding logic
- `app/features/microstructure/`: microstructure feature and signal policy
- `app/polymarket/`: prediction-market provider + mispricing logic
- `app/wallet_intel/`: wallet scoring and signals
- `app/event_signals/`: normalized event/news signals
- `app/simulation/mirofish_adapter.py`: advisory simulation adapter
- `app/portfolio_brain/`: capital allocation recommendations
- `app/promotion/`: promotion ladder
- `app/research/`, `app/replay/`, `app/optimization/`: research, replay, optimization

### Execution / controls / ops
- `app/risk/`: risk engine, locks, exposure manager
- `app/execution/`: approvals, paper execution, Telegram runtime controller, live adapter helpers
- `app/live/`: guarded-live controller, locks, reconciliation, rollout policy
- `app/shadow/`: shadow runner and service
- `app/ops/`: startup checks, recovery, ops status
- `app/agents/openclaw_bridge.py`: alerts, incidents, operator-note integration
- `app/provider_health/`: provider health snapshots and ingest-run tracking

### Persistence / API
- `app/persistence/models.py`: SQLAlchemy persistence models
- `app/persistence/repositories/`: repository layer for signals, risk, alpha, polymarket, wallets, provider health, portfolio brain, incidents, replay, backfill, etc.
- `app/api/routes/`: broad API surface for health, market data, risk, live, rollout, portfolio, analytics, replay, optimization, events, wallets, polymarket, microstructure, execution quality, provider health, system stream, incidents, and more

## 2. What Is Already Implemented

- Binance spot and futures market-data ingestion with health checks and REST fallback
- Core signal generation for crypto trend-follow + breakout
- Risk validation, lock history, and risk summaries
- Approval flow and paper execution
- Shadow execution path
- Guarded live controller scaffolding with lock manager and reconciliation
- Rollout phases and capital-scaling policy
- Portfolio state, allocation, analytics, and reporting
- TradingView-like features, alpha fusion, regime service
- Basis/funding and microstructure research layers
- Polymarket, wallet intelligence, event/news, provider health, portfolio brain, promotion, OpenClaw, and MiroFish service layers
- Persistence for most major entities with Alembic migrations through `20260408_0004`
- Operator dashboard-compatible API surface and system stream support

## 3. What Is Mock / Scaffold Only

- Polymarket execution is not present; current Polymarket support is market-data/opportunity research only
- Wallet intelligence real-provider path exists as a scaffold, but depends on external wallet datasets/APIs that are not guaranteed configured
- Event/news real-provider path exists as a scaffold, but concrete production feeds are optional and env-driven
- MiroFish remains advisory and optional
- OpenClaw is an orchestration bridge, not a trading source of truth
- Telegram runtime exists for local/operator control formatting and command handling, not as a proven production alert transport
- Many advanced strategy families are advisory and do not yet produce fully executable trade plans

## 4. What Looks Production-Ready

- Paper-first safety posture
- Binance market-data ingestion and health/fallback design
- Risk / approval / execution separation
- Persistence-backed API modules for core entities
- Provider-health snapshots and incident scaffolding
- Replay / research storage and reporting foundation
- Operator dashboard-compatible endpoints and stream architecture

## 5. What Is Unsafe or Incomplete Before Real Capital

- Live trading remains intentionally locked unless multiple explicit flags are enabled; this is correct and should remain so
- Several alpha sources still emit advisory research signals without executable trade plans
- Strategy selection above raw alpha sources was missing before the new `strategy_owner` layer
- Prediction-market execution and settlement realism remain incomplete
- Replay fidelity varies by dataset availability and should not be treated as venue-grade tick replay
- Wallet/event providers may degrade to mock/fallback modes depending on configuration
- Telegram/OpenClaw should be treated as operator tooling, not authorization truth

## 6. API Routes Currently Present

From `app/api/__init__.py`, the API currently includes routers for:
- `health`
- `ops`
- `system`
- `features`
- `alpha`
- `arbitrage`
- `microstructure`
- `polymarket`
- `wallets`
- `events`
- `regime`
- `analytics`
- `market-data`
- `live`
- `signals`
- `risk`
- `approvals`
- `positions`
- `trades`
- `pnl`
- `execution-quality`
- `control`
- `portfolio`
- `portfolio_brain`
- `promotion`
- `provider-health`
- `rollout`
- `replay`
- `research`
- `optimization`
- `reports`
- `shadow`
- `mirofish`
- `system_stream`
- `system_records`

## 7. Services Wired In `app/core/lifecycle.py`

On startup, the app wires:
- `MarketDataService`
- `SignalService`
- `FeatureService`
- `RegimeService`
- `BasisFundingService`
- `MicrostructureService`
- `ExecutionQualityService`
- `OpenClawBridge`
- `ProviderHealthService`
- `PolymarketService`
- `WalletIntelService`
- `EventSignalsService`
- `MiroFishAdapter`
- `AlphaFusionService`
- `RiskService`
- `PromotionService`
- `PortfolioBrainService`
- `ExecutionService`
- `ReplayService`
- `ResearchService`
- `OptimizationService`
- `ReportingService`
- `ShadowService`
- `PortfolioService`
- `AnalyticsService`
- `LiveRolloutPolicy`
- `LiveController`
- `StartupCheckService`
- `RecoveryService`
- `OpsService`

## 8. Config Flags Present In `app/config/settings.py`

The settings module already includes flags for:
- app/runtime basics (`APP_ENV`, `API_V1_PREFIX`, CORS, dashboard stream)
- market-data health, symbol/timeframe coverage, freshness windows
- signal-engine parameters
- feature extraction and alpha-fusion weights
- paper execution and persistence
- shadow mode
- guarded live enablement, arming, explicit approvals, slippage, reconciliation, rollout, and capital caps
- portfolio and analytics controls
- regime parameters
- promotion thresholds
- provider-health thresholds
- OpenClaw and MiroFish toggles
- Polymarket, wallet, event/news provider modes and thresholds
- basis/funding thresholds
- microstructure thresholds
- execution-quality thresholds
- risk-lock toggles and thresholds
- replay/backfill/provider-mode hardening

## 9. Persistence Tables / Repositories Present

Persistence models already cover:
- signals, risk assessments, approvals, trades, positions
- replay, optimization, reports, generic events
- live locks, rollout state, portfolio records, analytics
- alpha source readings, fused opportunities, feature runs, regime snapshots
- wallet profiles / observations / signals
- arbitrage opportunities
- event observations / signals
- Polymarket markets / snapshots / linked validations
- strategy allocations
- promotion reviews / statuses
- execution quality
- provider health snapshots / events / ingest runs
- risk lock events
- research experiments / runs / artifacts
- backfill jobs
- operator notes / incidents / alert history
- portfolio brain snapshots
- MiroFish simulation runs
- replay fidelity metadata
- microstructure feature snapshots

## 10. Tests Present

Current test coverage already includes:
- health and readiness endpoints
- market-data health and depth WebSocket behavior
- signal evaluation
- risk evaluation
- approval and execution flows
- live control, live locks, reconciliation
- rollout policy / endpoints / rollback
- reporting and analytics
- replay engine
- optimization and leaderboard
- persistence recovery
- shadow mode
- portfolio allocator/orchestration
- phase-specific intelligence platform tests
- remaining production-hardening tests
- migration smoke tests

## 11. Highest-Priority Gaps Before Real Capital

1. A single strategy-owner / selection layer above raw alpha producers
2. More realistic paper execution across both crypto and prediction-market paths
3. Consistent routing so advisory alpha cannot bypass risk/approval
4. Stronger replay parity with the live decision pipeline
5. More explicit live-governance evidence for promotion and provider health
6. Clear provider matrix separating real, mock, and paper-only paths

## 12. Exact Next Milestones

1. Add `app/strategy_owner/` to normalize, score, reject, and persist candidates before risk
2. Route executable candidates through `RiskService` only when a valid execution plan exists
3. Upgrade paper execution realism for spread, slippage, latency, depth, partial fills, and stale data
4. Add dedicated research-only latency-arbitrage and market-making modules
5. Strengthen replay so the same pipeline is used in research and paper execution
6. Expand risk, promotion, and documentation around real-capital readiness

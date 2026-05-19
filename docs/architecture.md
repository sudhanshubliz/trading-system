# Architecture

## Current Layers

- Execution and risk kernel
  - Existing `signals`, `risk`, `execution`, `live`, `portfolio`, `shadow`, `replay`, `optimization`, `reporting`, and `ops` modules remain the trading truth.
- Data and feature layer
  - `app/market_data` provides Binance data.
  - `app/features/tradingview_like` converts candles into research features.
- Intelligence layer
  - `app/regime` classifies market state.
  - `app/alpha_fusion` emits normalized source readings and fused opportunities.
  - `app/arbitrage` emits Binance basis/funding opportunities.
  - `app/features/microstructure` emits short-horizon order-book and trade-flow snapshots.
- Execution-quality and lock layer
  - `app/execution_quality` records fill quality across paper, shadow, replay, and live paths.
  - `app/risk` now applies Phase 2 stale-data, liquidity, volatility, execution-anomaly, and basis-integrity locks.
- Research layer
  - `app/research` persists experiment metadata, runs, and artifacts.
- Future strategy adapters
  - `app/wallet_intel`, `app/event_signals`, `app/provider_health`, `app/portfolio_brain`, `app/agents`, and `app/simulation` remain later-phase modules.

## Persistence

Two database tracks remain in place:

- `DATABASE_URL`
  - operational state such as market snapshots and system state
- `PERSISTENCE_DB_URL`
  - durable JSON-backed execution, reporting, and new Phase 1 intelligence records

Alembic now manages the persistence DB roadmap.

Phase 2 adds persisted records for:

- `microstructure_feature_snapshots`
- `execution_quality_records`
- `risk_lock_events`
- additional `arbitrage_opportunities` usage for basis/funding

## Safety

- paper-first
- shadow isolated from paper/live
- live disabled by default
- live still gated by approval, locks, rollout, and controller checks
- intelligence services create candidates and explanations only
- replay microstructure and funding are explicit approximations, not fabricated exchange precision

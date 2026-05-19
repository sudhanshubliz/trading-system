# Risk Locks

## Phase 2 Locks

Phase 2 extends the risk layer with persisted lock events under `risk_lock_events`.

New lock types:

- `stale_data_lock`
- `volatility_shock_lock`
- `execution_anomaly_lock`
- `liquidity_thin_lock`
- `basis_data_integrity_lock`

## Trigger Logic

`stale_data_lock`

- stale or missing order book
- stale basis/funding inputs

`volatility_shock_lock`

- realized short-window volatility above threshold
- toxic-flow or unstable-quote microstructure states

`execution_anomaly_lock`

- repeated low execution-quality scores
- repeated slippage / partial-fill degradation

`liquidity_thin_lock`

- insufficient depth
- spread beyond configured maximum

`basis_data_integrity_lock`

- missing funding snapshot
- inconsistent or stale basis inputs

## Behavior

- locks can veto a trade even when the underlying strategy signal is otherwise valid
- lock events include scope, reason, severity, timestamps, and metrics snapshot
- current and historical lock views are exposed via:
  - `GET /api/v1/risk/locks/current`
  - `GET /api/v1/risk/locks/history`

## Safety Notes

- locks are additive on top of existing risk-engine checks
- this phase does not weaken any prior live guardrails

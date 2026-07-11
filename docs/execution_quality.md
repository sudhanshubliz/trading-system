# Execution Quality

## Scope

Phase 2 adds execution-quality tracking in `app/execution_quality`.

Records are written for:

- paper fills
- shadow decisions / executions
- replay fills
- live fills when guarded live execution is active

## Recorded Fields

- trade and order linkage
- symbol and strategy
- mode
- intended action
- execution policy
- decision / submit / fill timestamps
- intended price
- arrival mid price
- actual fill price
- expected and realized slippage
- entry/exit fee attribution in the associated trade and position records
- gross P&L, net P&L, and simulated slippage-cost attribution
- latency
- partial-fill ratio
- fill-quality score
- notes and explanation

## Scoring

The fill-quality score penalizes:

- slippage beyond expected range
- slow execution
- incomplete fills
- wide-spread conditions at execution time

## APIs

- `GET /api/v1/execution/quality`
- `GET /api/v1/execution/quality/{trade_id}`

Supported list filters:

- `mode`
- `symbol`
- `strategy_name`
- `start_time`
- `end_time`
- `min_score`
- `max_score`

## Safety Notes

- execution-quality records do not change orders directly
- they are used by Phase 2 anomaly locks and operator review flows
- repeated poor quality can trigger `execution_anomaly_lock`
- paper, shadow, and replay net P&L deduct both entry and exit fees
- simulated adverse slippage changes the fill price and is reported separately; it is not deducted from P&L a second time
- live fills are never assigned synthetic paper costs because exchange-confirmed execution remains the source of truth

# Microstructure Engine

## Scope

Phase 2 adds a Binance microstructure engine in `app/features/microstructure`.

It computes short-horizon features from maintained order-book and trade-flow views:

- top-of-book spread
- relative spread
- top-level and top-N imbalance
- order-book pressure
- microprice
- book slope
- depth concentration
- depth depletion
- quote instability
- signed volume and trade-flow imbalance
- burst score
- realized short volatility
- adverse-selection proxy
- stale-book detection

## Market States

- `normal`
- `thin_liquidity`
- `spread_wide`
- `imbalance_buy_pressure`
- `imbalance_sell_pressure`
- `toxic_flow_risk`
- `unstable_quotes`
- `stale_data`

## Signal Policies

- `no_trade`
- `passive_buy_bias`
- `passive_sell_bias`
- `taker_buy_momentum`
- `taker_sell_momentum`
- `spread_capture_only`
- `unsafe_to_trade`

## Persistence And APIs

- persisted in `microstructure_feature_snapshots`
- emitted into `alpha_source_readings` as `source_name=binance_microstructure`
- queried via:
  - `GET /api/v1/microstructure/current`
  - `GET /api/v1/microstructure/history`
  - `GET /api/v1/alpha/sources?source=binance_microstructure`

## Safety Notes

- stale or unstable microstructure states are intended to reduce or veto trading, not encourage it
- the engine is explainable and rule-based
- it is designed to feed risk and alpha fusion, not to bypass execution controls

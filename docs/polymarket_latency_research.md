# Polymarket Latency-Arbitrage Research

## Status

This strategy is paper/research only. It does not implement Polymarket order signing or live CLOB execution, and it makes no profitability claim.

Social-media reports of very large returns or fixed win-rate thresholds are not evidence that a strategy remains profitable. Paper results must include fees, spread, depth, latency, partial fills, losing periods, and out-of-sample evaluation.

## Research Model

The service maps only BTC/ETH binary markets with an explicit 5- or 15-minute duration. It requires:

- fresh Binance ticker data
- sampled 30-second, 1-minute, and 5-minute reference-price history
- a mapped threshold and expiry
- fresh Polymarket CLOB WebSocket books
- two-sided prices
- minimum depth and bounded spread
- healthy real Polymarket provider data

Fair probability uses distance from threshold, recent realized movement, realized volatility, and time to expiry. This is an explainable approximation, not an oracle.

## Edge Calculation

For the selected YES or NO outcome:

1. Walk executable asks for the configured paper notional.
2. Reject incomplete fills.
3. Calculate entry and estimated exit fees using the probability-dependent fee curve.
4. Add observed book slippage and a configurable execution buffer.
5. Require net edge after all modeled costs.

The resulting opportunity records fair probability, market midpoint, simulated fill, fee/slippage estimates, fill ratio, book source, reference fidelity, and every rejection reason.

## Pipeline

```text
LatencyArbitrageService
  -> StrategyDecisionCandidate
  -> StrategyOwnerService
  -> RiskService
  -> operator approval
  -> shared paper/shadow ExecutionService
```

The risk engine caps prediction-market paper notional independently, carries cost metadata into the trade plan, and hard-rejects `paper_only` candidates in live mode. Paper fills use the selected outcome book and probability-dependent entry/exit fees.

## Configuration

```dotenv
LATENCY_ARB_ENABLED=false
LATENCY_ARB_PAPER_ONLY=true
LATENCY_ARB_MIN_NET_EDGE_BPS=800
LATENCY_ARB_MIN_DEPTH_USD=5000
LATENCY_ARB_MAX_SPREAD_BPS=300
LATENCY_ARB_MAX_DATA_AGE_SEC=10
LATENCY_ARB_SYMBOLS=BTCUSDT,ETHUSDT
LATENCY_ARB_MAX_MARKETS=20
LATENCY_ARB_ALLOWED_DURATIONS_MINUTES=5,15
LATENCY_ARB_MIN_TIME_TO_EXPIRY_SEC=60
LATENCY_ARB_PAPER_ORDER_NOTIONAL_USD=50
LATENCY_ARB_EXECUTION_BUFFER_BPS=25
LATENCY_ARB_REQUIRE_REALTIME_REFERENCE=true
LATENCY_ARB_REQUIRE_STREAMING_BOOK=true
```

Defaults deliberately favor false negatives. Do not lower thresholds because no opportunities appear; calibrate only with stored out-of-sample evidence.

## Operator Validation

```bash
curl -X POST http://127.0.0.1:3030/api/v1/latency-arb/evaluate
curl http://127.0.0.1:3030/api/v1/latency-arb/opportunities
curl http://127.0.0.1:3030/api/v1/latency-arb/summary
curl -X POST http://127.0.0.1:3030/api/v1/strategy-owner/evaluate
curl http://127.0.0.1:3030/api/v1/strategy-owner/rejections
```

Promotion remains blocked until there is sufficient realistic paper and shadow evidence. The live controller remains unchanged and cannot execute this paper-only family.

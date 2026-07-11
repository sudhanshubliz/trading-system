# Strategy Owner

## Purpose

`StrategyOwnerService` is an institutional-style decision layer that sits above raw alpha producers and below risk/approval. It does not place trades. Its job is to:

- collect opportunities from multiple existing services
- normalize them into a common candidate shape
- score them on expected value, confidence, liquidity, freshness, execution quality, provider health, regime, exposure, and historical performance
- reject weak candidates with explicit reasons
- forward only executable candidates to `RiskService`
- persist both candidates and decisions for operator review

## Current Source Coverage

The initial implementation collects from:
- `SignalService`
- `AlphaFusionService`
- `BasisFundingService`
- `MicrostructureService`
- `PolymarketService`
- `WalletIntelService`
- `EventSignalsService`
- `MiroFishAdapter` when available

## Decision Statuses

- `accepted_for_monitoring`: strong enough to keep/watch, but not forwarded to risk
- `accepted_for_risk`: executable and approved through `RiskService`
- `rejected`: strategy-owner filters rejected the candidate
- `rejected_by_risk`: strategy-owner accepted it, but risk vetoed it

## Persistence

The service persists:
- `strategy_owner_candidates`
- `strategy_owner_decisions`

This creates an audit trail for why a candidate was kept, rejected, or blocked by risk.

## API

- `GET /api/v1/strategy-owner/candidates`
- `GET /api/v1/strategy-owner/decisions`
- `POST /api/v1/strategy-owner/evaluate`
- `GET /api/v1/strategy-owner/summary`
- `GET /api/v1/strategy-owner/rejections`

## Safety Notes

- Strategy owner does not bypass `RiskService`
- advisory sources remain advisory unless an executable trade plan exists
- live trading stays disabled unless the existing live flags and approval path are explicitly enabled

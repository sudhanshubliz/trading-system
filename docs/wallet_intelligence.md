# Wallet Intelligence

## Scope

Phase 3 adds wallet research under `app/wallet_intel` with:

- provider abstraction
- mock wallet activity feed
- real-provider scaffold
- wallet profile scoring
- wallet observations
- wallet-driven signals and leaderboards

## Scoring Dimensions

- persistence
- timing quality
- sizing discipline
- concentration
- crowding risk
- overall quality score

## Signal Modes

- `follow`
- `fade`
- `ignore`
- `monitor_only`

The chosen action is controlled by quality score, crowding, and `WALLET_SIGNAL_MODE`.

## Persistence

- `wallet_profiles`
- `wallet_observations`
- `wallet_signals`

## APIs

- `GET /api/v1/wallets`
- `GET /api/v1/wallets/{wallet_id}`
- `GET /api/v1/wallets/leaderboard`
- `GET /api/v1/wallets/signals`
- `GET /api/v1/wallets/observations`

## Safety

Wallet data is never treated as authoritative execution truth. It is one research input among many and can be vetoed by provider health, risk locks, or conflicting event context.

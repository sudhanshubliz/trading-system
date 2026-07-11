# $5,000 Native-Cost Walk-Forward Assessment

Assessment date: 2026-07-11

## Decision

**No-go for live trading.** The fixed BTCUSDT/ETHUSDT strategy set failed the 90-day after-cost walk-forward gate. Live trading remained disabled and unarmed throughout this assessment.

## Study Scope

- Initial simulated account: `$5,000`
- Target: average at least `$5/day` after costs
- Replay interval: `2026-04-11T18:55:00Z` through `2026-07-10T18:55:00Z`
- Walk-forward windows: three chronological 30-day folds
- Symbols: `BTCUSDT`, `ETHUSDT`
- Timeframes: `5m`, `15m`, `1h`
- Inputs: official Binance public spot and USD-M futures klines
- Fidelity: `high_fidelity_best_effort`
- Strategy parameters: fixed for the full period; no fold-by-fold selection or refit
- Initial and exit costs: native paper/replay accounting, not an external result overlay

## Full-Period Results

| Metric | Result |
| --- | ---: |
| Closed trades | `87` |
| Gross realized P&L before fees | `-$580.09` |
| Fees | `-$868.35` |
| Net realized P&L | `-$1,448.44` |
| Average net P&L per day | `-$16.09` |
| Ending balance | `$3,551.56` |
| Expectancy per trade | `-$16.65` |
| Profit factor | `0.3803` |
| Maximum drawdown | `30.80%` |
| Positive folds | `0 / 3` (minimum required: `2 / 3`) |
| Round-trip turnover | `$868,104.46` |
| Slippage-cost attribution | `$301.30` |

The `$5/day` target was not met. Gross realized P&L is already negative before fees, so lower exchange commissions alone would not make this configuration acceptable.

Slippage changes the simulated entry and exit fill prices and is therefore embedded in gross and net P&L. The separate slippage value is attribution only and is not deducted twice.

## Chronological Folds

| Fold | Dates (UTC) | Trades | Net P&L | Expectancy | Profit factor | Max drawdown | Passed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | Apr 11 to May 11 | 32 | `-$586.70` | `-$18.33` | `0.2659` | `11.73%` | No |
| 2 | May 11 to Jun 10 | 25 | `-$5.54` | `-$0.22` | `0.9881` | `5.43%` | No |
| 3 | Jun 10 to Jul 10 | 30 | `-$856.20` | `-$28.54` | `0.2006` | `18.36%` | No |

None of the three forward windows produced positive after-cost expectancy.

## Gate Blockers

- `full_period_expectancy_not_positive`
- `full_period_profit_factor_below_minimum`
- `full_period_drawdown_exceeded`
- `walk_forward_positive_folds_below_minimum`

The duration and minimum-trade requirements were met, but the performance and risk requirements were not.

## Hardening Completed

- Paper, shadow, and replay P&L now deduct entry and exit fees natively.
- Adverse entry and exit slippage is embedded in fill prices and reported separately for attribution.
- The shared `RiskService` path rejects candidates whose expected edge does not clear modeled round-trip costs.
- A per-symbol/strategy cooldown reduces repeated turnover through both direct and strategy-owner paths.
- Replay candles become visible only at their close boundary; completed higher-timeframe OHLC is not exposed at candle open.
- Walk-forward reports persist chronological fold metrics, native costs, turnover, fidelity notes, and explicit blockers.
- A fresh shadow evidence window excludes historical trades recorded before the current shadow start.

## Fidelity Limits

- Historical order books and queue position are not reconstructed. Replay microstructure uses deterministic synthetic depth derived from candle price and volume.
- Funding/basis uses spot-versus-futures candle approximations where historical funding snapshots are unavailable.
- Exact account-specific Binance commissions were not queried. The assessment uses the repository's configured `10 bps` fee per side.
- Slippage is deterministic and conservative, not a claim of exact venue fills.
- This study uses a fixed historical window and is evidence for rejection, not a performance forecast.

The compact reproducibility artifact is `artifacts/replay/walk_forward_20260710T185500Z.json`.

## Runtime Verification

- Backend: healthy on `127.0.0.1:3030`, default mode `paper`, simulated balance `$5,000`
- Binance market data: healthy for BTCUSDT and ETHUSDT; ticker, order book, `5m`, `15m`, and `1h` data fresh
- Shared active risk locks: `0`
- Live: `enabled=false`, `armed=false`, `can_execute=false`; `LIVE_NOT_ARMED` remains active
- Shadow: fresh evidence window running from `2026-07-11T06:57:41Z`; first cycle completed without error, with no forced trades
- Initial live-market evaluation: `0` core signals and `0` risk assessments; no trade was forced
- Verification: `117` backend tests passed; dashboard TypeScript check passed

## Required Before Any Live Trade

1. Do not tune thresholds against this same failed 90-day sample and then call it validation.
2. Research a materially improved hypothesis using separate development data.
3. Test the frozen replacement on untouched walk-forward data with positive after-cost expectancy, acceptable drawdown, and consistent folds.
4. Complete a fresh shadow window of at least 7 days and 50 closed trades with positive expectancy and profit factor at or above 1.
5. Verify account-specific Binance commissions without exposing credentials.
6. Keep live disabled until replay, shadow, promotion, provider-health, risk-lock, and explicit operator approval gates all pass.

The system must not be relied upon for rent, food, or guaranteed daily income.

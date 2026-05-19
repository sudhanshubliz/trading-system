# Feature Engine

## Purpose

The Phase 1 feature engine brings TradingView-style feature extraction into Python without turning indicators into direct trade commands.

## Implemented Features

- EMA fast/slow
- SMA fast/slow
- RSI
- MACD, signal, histogram
- ATR and ATR percent
- VWAP and VWAP gap
- Donchian upper/lower/mid
- Bollinger upper/mid/lower and width
- Keltner upper/mid/lower and width
- squeeze state
- breakout distances and bias
- range compression
- simple market structure
- order-block and FVG research placeholders

## Flow

1. Load candle history for configured timeframes.
2. Compute deterministic feature vectors per timeframe.
3. Build an `AlphaFeatureSnapshot`.
4. Persist a `feature_runs` record.

## Notes

- The engine is intentionally explainable and deterministic.
- Placeholder structure signals are clearly labeled as research placeholders.

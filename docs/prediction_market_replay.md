# Prediction Market Replay

## Scope

Prediction-market replay is now explicitly fidelity-scoped and persists metadata about what external evidence was available.

## Fidelity Modes

- `low_fidelity`
  - snapshot-level dislocation checks only
  - no claim of book reconstruction
- `medium`
  - snapshot plus annotation replay
  - event and wallet observations can participate when supplied
- `high_fidelity_best_effort`
  - uses every available stored snapshot and annotation
  - still does not claim order-by-order venue precision

## What It Can Replay

- stored Polymarket market snapshots
- persisted mispricing opportunities
- wallet observations and signals
- event observations and event signals
- fused research decisions derived from stored artifacts

## Fidelity Limits

- no claim of exact historical order-book queue position
- no claim of perfect discovery-time reconstruction for external news or wallet activity
- replay quality depends on what was persisted at observation time
- the persisted `precision_claim` tells operators what level of confidence is justified

## Design Rule

The system documents these limits explicitly instead of faking precision.

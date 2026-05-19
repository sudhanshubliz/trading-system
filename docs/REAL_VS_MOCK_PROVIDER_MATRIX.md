# Real vs Mock Provider Matrix

This matrix classifies the current provider posture in the repo. The goal is operational honesty: what is real, what is fallback-capable, and what should remain paper-only.

| Provider / Capability | Current Mode | Notes |
| --- | --- | --- |
| Binance spot market data | real | REST + WebSocket implementation exists and is actively used. Safe for paper and research. |
| Binance futures market data | real | Futures REST integration exists for candles, funding, and mark-price context. Safe for paper and research. |
| Binance execution | unsafe for live | Live adapter scaffolding exists, but guarded-live controls must remain explicit. Safe path is paper/shadow first. |
| Polymarket market data | auto_fallback | Real and mock providers exist. Real normalization is implemented, but operator should expect env-driven fallback when unavailable. |
| Polymarket CLOB execution | missing | Research/opportunity support exists. Direct production execution is not implemented and should not be assumed safe. |
| Wallet intelligence | auto_fallback | Mock provider is reliable locally. Real provider path depends on external dataset/API quality and should be treated as advisory. |
| Event/news feed | auto_fallback | Mock feed works locally. Real feed adapters exist, but concrete production quality depends on feed configuration. |
| OpenClaw | mock | Dry-run/orchestration bridge exists. It is not the source of trading truth and should stay operator-facing. |
| MiroFish | mock | Advisory simulation adapter only. Optional and non-binding by design. |
| Telegram | safe for paper only | Runtime/controller utilities exist, but this is not a hardened external notification provider. Do not treat as live-trading authority. |

## Operational Classification Summary

- `real`: implemented against concrete external APIs and used as part of normal platform operation
- `mock`: local/dev-safe only
- `auto_fallback`: real provider preferred, but safe fallback behavior is part of the design
- `missing`: no concrete production implementation
- `unsafe for live`: code exists, but operational controls or venue-specific validation are not strong enough for unattended live use
- `safe for paper only`: acceptable for internal workflows or paper trading, but not yet a production-trading dependency

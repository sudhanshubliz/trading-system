# Provider Interfaces

## Principle

When a provider is not fully wired yet, the repo should still expose:

- a typed boundary
- safe defaults
- mock or stub behavior
- clear TODO extension points

## Phase 1 Status

Scaffolded interfaces and packages now exist for:

- Polymarket data
- wallet intelligence
- event/news providers
- OpenClaw orchestration
- MiroFish simulation

## Safety

- provider stubs never force live execution
- missing providers should degrade to neutral or empty outputs, not hidden behavior

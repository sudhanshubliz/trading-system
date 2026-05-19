# Event Signals

## Scope

Phase 3 adds a normalized event/news framework under `app/event_signals` with:

- provider abstraction
- mock headlines and macro-style events
- real-provider scaffold
- normalized event model
- event-window classification
- decay-aware event signal generation

## Event Windows

- `pre_event`
- `during_event`
- `post_event`
- `stale_event`

## Signal Logic

Signals are generated from:

- event importance
- relevance to the target market or symbol
- sentiment when available
- timeliness decay

## Persistence

- `event_observations`
- `event_signals`

## APIs

- `GET /api/v1/events`
- `GET /api/v1/events/{event_id}`
- `GET /api/v1/events/signals`
- `GET /api/v1/events/providers/health`

## Safety

Event inputs are advisory and decay over time. Stale events should not dominate fused decisions.

# Event Real Provider

The event/news subsystem now supports real feed ingestion while keeping the mock provider available for local and CI workflows.

## Current Real Paths

- JSON news feeds
- RSS/Atom headline feeds
- macro calendar JSON feeds
- custom external event JSON feeds

## Normalization

All feeds are mapped into the existing normalized event schema:

- `event_id`
- `source`
- `title`
- `summary`
- `category`
- `event_type`
- `event_time`
- `detection_time`
- `entities`
- `importance_score`
- `sentiment_score`
- `relevance_score`
- `event_window_state`

## Data Quality Controls

- duplicate suppression inside the configured dedupe window
- missing timestamp fallback handling
- stale-event filtering
- provenance metadata for downstream debugging

# Promotion Ladder

## Stages

1. `research`
2. `paper`
3. `shadow`
4. `guarded_live`
5. `scaled_live`

## Phase 3 Implementation

`app/promotion/service.py` now evaluates strategy readiness from:

- sample count
- net expectancy after costs
- drawdown
- execution quality
- provider health
- incident count

## Persistence

- `strategy_promotion_status`
- `promotion_reviews`

## APIs

- `GET /api/v1/promotion/status`
- `POST /api/v1/promotion/review`
- `GET /api/v1/promotion/ladder`

## Constraint

Promotion recommendations are advisory records. They do not bypass the existing guarded-live and approval workflow.

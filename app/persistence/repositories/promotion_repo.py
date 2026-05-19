from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import PromotionReviewRecord, StrategyPromotionStatusRecord
from app.promotion.types import PromotionReview, StrategyPromotionStatus


class PromotionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_status(self, status: StrategyPromotionStatus, *, session: Session | None = None) -> StrategyPromotionStatus:
        return self._with_session(session, lambda db: self._upsert_status(db, status))

    def list_status(self, *, session: Session | None = None) -> list[StrategyPromotionStatus]:
        return self._with_session(session, self._list_status) or []

    def get_status(self, strategy_name: str, *, session: Session | None = None) -> StrategyPromotionStatus | None:
        return self._with_session(session, lambda db: self._get_status(db, strategy_name))

    def append_review(self, review: PromotionReview, *, session: Session | None = None) -> PromotionReview:
        return self._with_session(session, lambda db: self._append_review(db, review))

    def list_reviews(self, *, limit: int = 100, session: Session | None = None) -> list[PromotionReview]:
        return self._with_session(session, lambda db: self._list_reviews(db, limit=limit)) or []

    def _upsert_status(self, session: Session, status: StrategyPromotionStatus) -> StrategyPromotionStatus:
        record = session.get(StrategyPromotionStatusRecord, status.strategy_name)
        payload = serialize_payload(status)
        if record is None:
            session.add(
                StrategyPromotionStatusRecord(
                    strategy_name=status.strategy_name,
                    current_stage=status.current_stage,
                    eligible_for_promotion="true" if status.eligible_for_promotion else "false",
                    last_review_at=status.last_review_at,
                    updated_at=utc_now(),
                    payload_json=payload,
                )
            )
        else:
            record.current_stage = status.current_stage
            record.eligible_for_promotion = "true" if status.eligible_for_promotion else "false"
            record.last_review_at = status.last_review_at
            record.updated_at = utc_now()
            record.payload_json = payload
        return status

    def _list_status(self, session: Session) -> list[StrategyPromotionStatus]:
        query = select(StrategyPromotionStatusRecord).order_by(StrategyPromotionStatusRecord.updated_at.desc())
        return [self._deserialize_status(record.payload_json) for record in session.scalars(query).all()]

    def _get_status(self, session: Session, strategy_name: str) -> StrategyPromotionStatus | None:
        record = session.get(StrategyPromotionStatusRecord, strategy_name)
        return self._deserialize_status(record.payload_json) if record is not None else None

    def _append_review(self, session: Session, review: PromotionReview) -> PromotionReview:
        session.add(
            PromotionReviewRecord(
                review_id=review.review_id,
                strategy_name=review.strategy_name,
                stage_name=review.stage_name,
                decision=review.decision,
                reviewed_at=review.reviewed_at,
                payload_json=serialize_payload(review),
            )
        )
        return review

    def _list_reviews(self, session: Session, *, limit: int) -> list[PromotionReview]:
        query = select(PromotionReviewRecord).order_by(PromotionReviewRecord.reviewed_at.desc()).limit(max(limit, 0))
        return [self._deserialize_review(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize_status(self, payload_json: str) -> StrategyPromotionStatus:
        payload = deserialize_payload(payload_json)
        payload["last_review_at"] = ensure_aware_datetime(payload.get("last_review_at"))
        return StrategyPromotionStatus(**payload)

    def _deserialize_review(self, payload_json: str) -> PromotionReview:
        payload = deserialize_payload(payload_json)
        payload["reviewed_at"] = ensure_aware_datetime(payload.get("reviewed_at"))
        return PromotionReview(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)


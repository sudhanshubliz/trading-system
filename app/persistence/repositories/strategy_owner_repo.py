from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload, utc_now
from app.persistence.models import StrategyOwnerCandidateRecord, StrategyOwnerDecisionRecord
from app.strategy_owner.types import StrategyDecisionCandidate, StrategyOwnerDecision


class StrategyOwnerRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_candidate(self, candidate: StrategyDecisionCandidate, *, session: Session | None = None) -> StrategyDecisionCandidate:
        return self._with_session(session, lambda db: self._upsert_candidate(db, candidate))

    def append_decision(self, decision: StrategyOwnerDecision, *, session: Session | None = None) -> StrategyOwnerDecision:
        return self._with_session(session, lambda db: self._append_decision(db, decision))

    def list_candidates(
        self,
        *,
        strategy_family: str | None = None,
        source_name: str | None = None,
        symbol_or_market: str | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[StrategyDecisionCandidate]:
        return self._with_session(
            session,
            lambda db: self._list_candidates(
                db,
                strategy_family=strategy_family,
                source_name=source_name,
                symbol_or_market=symbol_or_market,
                limit=limit,
            ),
        ) or []

    def list_decisions(
        self,
        *,
        status: str | None = None,
        strategy_family: str | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[StrategyOwnerDecision]:
        return self._with_session(
            session,
            lambda db: self._list_decisions(db, status=status, strategy_family=strategy_family, limit=limit),
        ) or []

    def _upsert_candidate(self, session: Session, candidate: StrategyDecisionCandidate) -> StrategyDecisionCandidate:
        now = utc_now()
        record = session.get(StrategyOwnerCandidateRecord, candidate.candidate_id)
        payload = serialize_payload(candidate)
        if record is None:
            record = StrategyOwnerCandidateRecord(
                candidate_id=candidate.candidate_id,
                source_name=candidate.source_name,
                strategy_family=candidate.strategy_family,
                symbol_or_market=candidate.symbol_or_market,
                direction=candidate.direction,
                overall_score=candidate.overall_score,
                confidence=candidate.confidence,
                tradable=str(candidate.tradable).lower(),
                generated_at=candidate.timestamp,
                payload_json=payload,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.source_name = candidate.source_name
            record.strategy_family = candidate.strategy_family
            record.symbol_or_market = candidate.symbol_or_market
            record.direction = candidate.direction
            record.overall_score = candidate.overall_score
            record.confidence = candidate.confidence
            record.tradable = str(candidate.tradable).lower()
            record.generated_at = candidate.timestamp
            record.payload_json = payload
            record.updated_at = now
        return candidate

    def _append_decision(self, session: Session, decision: StrategyOwnerDecision) -> StrategyOwnerDecision:
        now = utc_now()
        existing = session.get(StrategyOwnerDecisionRecord, decision.decision_id)
        payload = serialize_payload(decision)
        if existing is None:
            existing = StrategyOwnerDecisionRecord(
                decision_id=decision.decision_id,
                candidate_id=decision.candidate_id,
                source_name=decision.source_name,
                strategy_family=decision.strategy_family,
                symbol_or_market=decision.symbol_or_market,
                status=decision.status,
                overall_score=decision.overall_score,
                forwarded_to_risk=str(decision.forwarded_to_risk).lower(),
                rejection_reason=decision.rejection_reason,
                decided_at=decision.timestamp,
                payload_json=payload,
                created_at=now,
            )
            session.add(existing)
        else:
            existing.candidate_id = decision.candidate_id
            existing.source_name = decision.source_name
            existing.strategy_family = decision.strategy_family
            existing.symbol_or_market = decision.symbol_or_market
            existing.status = decision.status
            existing.overall_score = decision.overall_score
            existing.forwarded_to_risk = str(decision.forwarded_to_risk).lower()
            existing.rejection_reason = decision.rejection_reason
            existing.decided_at = decision.timestamp
            existing.payload_json = payload
        return decision

    def _list_candidates(
        self,
        session: Session,
        *,
        strategy_family: str | None,
        source_name: str | None,
        symbol_or_market: str | None,
        limit: int,
    ) -> list[StrategyDecisionCandidate]:
        query = select(StrategyOwnerCandidateRecord)
        if strategy_family is not None:
            query = query.where(StrategyOwnerCandidateRecord.strategy_family == strategy_family)
        if source_name is not None:
            query = query.where(StrategyOwnerCandidateRecord.source_name == source_name)
        if symbol_or_market is not None:
            query = query.where(StrategyOwnerCandidateRecord.symbol_or_market == symbol_or_market)
        query = query.order_by(StrategyOwnerCandidateRecord.generated_at.desc()).limit(max(limit, 0))
        return [self._deserialize_candidate(record.payload_json) for record in session.scalars(query).all()]

    def _list_decisions(
        self,
        session: Session,
        *,
        status: str | None,
        strategy_family: str | None,
        limit: int,
    ) -> list[StrategyOwnerDecision]:
        query = select(StrategyOwnerDecisionRecord)
        if status is not None:
            query = query.where(StrategyOwnerDecisionRecord.status == status)
        if strategy_family is not None:
            query = query.where(StrategyOwnerDecisionRecord.strategy_family == strategy_family)
        query = query.order_by(StrategyOwnerDecisionRecord.decided_at.desc()).limit(max(limit, 0))
        return [self._deserialize_decision(record.payload_json) for record in session.scalars(query).all()]

    def _deserialize_candidate(self, payload_json: str) -> StrategyDecisionCandidate:
        payload = deserialize_payload(payload_json)
        payload["timestamp"] = ensure_aware_datetime(payload.get("timestamp"))
        return StrategyDecisionCandidate(**payload)

    def _deserialize_decision(self, payload_json: str) -> StrategyOwnerDecision:
        payload = deserialize_payload(payload_json)
        payload["timestamp"] = ensure_aware_datetime(payload.get("timestamp"))
        return StrategyOwnerDecision(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

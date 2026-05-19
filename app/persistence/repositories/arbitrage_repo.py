from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.arbitrage.types import BasisFundingOpportunity
from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import ArbitrageOpportunityRecord


class ArbitrageRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_opportunity(
        self,
        opportunity: BasisFundingOpportunity,
        *,
        session: Session | None = None,
    ) -> BasisFundingOpportunity:
        return self._with_session(session, lambda db: self._upsert(db, opportunity))

    def list_opportunities(
        self,
        *,
        symbol: str | None = None,
        tradable: bool | None = None,
        min_confidence: float | None = None,
        detected_after: datetime | None = None,
        limit: int = 100,
        session: Session | None = None,
    ) -> list[BasisFundingOpportunity]:
        return self._with_session(
            session,
            lambda db: self._list(
                db,
                symbol=symbol,
                tradable=tradable,
                min_confidence=min_confidence,
                detected_after=detected_after,
                limit=limit,
            ),
        ) or []

    def get_opportunity(self, opportunity_id: str, *, session: Session | None = None) -> BasisFundingOpportunity | None:
        return self._with_session(session, lambda db: self._get(db, opportunity_id))

    def _upsert(self, session: Session, opportunity: BasisFundingOpportunity) -> BasisFundingOpportunity:
        record = session.get(ArbitrageOpportunityRecord, opportunity.opportunity_id)
        payload = serialize_payload(opportunity)
        if record is None:
            session.add(
                ArbitrageOpportunityRecord(
                    opportunity_id=opportunity.opportunity_id,
                    market="binance",
                    symbol_or_market=opportunity.symbol,
                    direction=opportunity.recommended_direction,
                    confidence=opportunity.confidence,
                    status="tradable" if opportunity.tradable else "monitor",
                    detected_at=opportunity.timestamp,
                    payload_json=payload,
                )
            )
        else:
            record.market = "binance"
            record.symbol_or_market = opportunity.symbol
            record.direction = opportunity.recommended_direction
            record.confidence = opportunity.confidence
            record.status = "tradable" if opportunity.tradable else "monitor"
            record.detected_at = opportunity.timestamp
            record.payload_json = payload
        return opportunity

    def _list(
        self,
        session: Session,
        *,
        symbol: str | None,
        tradable: bool | None,
        min_confidence: float | None,
        detected_after: datetime | None,
        limit: int,
    ) -> list[BasisFundingOpportunity]:
        query = select(ArbitrageOpportunityRecord).where(ArbitrageOpportunityRecord.market == "binance")
        if symbol is not None:
            query = query.where(ArbitrageOpportunityRecord.symbol_or_market == symbol.upper())
        if detected_after is not None:
            query = query.where(ArbitrageOpportunityRecord.detected_at >= detected_after)
        query = query.order_by(ArbitrageOpportunityRecord.detected_at.desc()).limit(max(limit, 0))
        items = [self._deserialize(record.payload_json) for record in session.scalars(query).all()]
        if tradable is not None:
            items = [item for item in items if item.tradable is tradable]
        if min_confidence is not None:
            items = [item for item in items if item.confidence >= min_confidence]
        return items

    def _get(self, session: Session, opportunity_id: str) -> BasisFundingOpportunity | None:
        record = session.get(ArbitrageOpportunityRecord, opportunity_id)
        if record is None:
            return None
        return self._deserialize(record.payload_json)

    def _deserialize(self, payload_json: str) -> BasisFundingOpportunity:
        payload = deserialize_payload(payload_json)
        payload["timestamp"] = ensure_aware_datetime(payload.get("timestamp"))
        return BasisFundingOpportunity(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import deserialize_payload, ensure_aware_datetime, serialize_payload
from app.persistence.models import ArbitrageOpportunityRecord, LinkedMarketValidationRecord, PolymarketMarketRecord, PolymarketMarketSnapshotRecord
from app.polymarket.types import LinkedMarketValidation, PolymarketMarket, PolymarketOpportunity, PolymarketOrderBook


class PolymarketRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_market(self, market: PolymarketMarket, *, session: Session | None = None) -> PolymarketMarket:
        return self._with_session(session, lambda db: self._upsert_market(db, market))

    def list_markets(self, *, session: Session | None = None) -> list[PolymarketMarket]:
        return self._with_session(session, self._list_markets) or []

    def get_market(self, market_id: str, *, session: Session | None = None) -> PolymarketMarket | None:
        return self._with_session(session, lambda db: self._get_market(db, market_id))

    def upsert_snapshot(self, snapshot: PolymarketOrderBook, *, session: Session | None = None) -> PolymarketOrderBook:
        return self._with_session(session, lambda db: self._upsert_snapshot(db, snapshot))

    def upsert_opportunity(self, opportunity: PolymarketOpportunity, *, session: Session | None = None) -> PolymarketOpportunity:
        return self._with_session(session, lambda db: self._upsert_opportunity(db, opportunity))

    def list_opportunities(self, *, market: str = "polymarket", limit: int = 100, session: Session | None = None) -> list[PolymarketOpportunity]:
        return self._with_session(session, lambda db: self._list_opportunities(db, market=market, limit=limit)) or []

    def get_opportunity(self, opportunity_id: str, *, session: Session | None = None) -> PolymarketOpportunity | None:
        return self._with_session(session, lambda db: self._get_opportunity(db, opportunity_id))

    def upsert_linked_validation(self, validation: LinkedMarketValidation, *, session: Session | None = None) -> LinkedMarketValidation:
        return self._with_session(session, lambda db: self._upsert_validation(db, validation))

    def _upsert_market(self, session: Session, market: PolymarketMarket) -> PolymarketMarket:
        record = session.get(PolymarketMarketRecord, market.market_id)
        payload = serialize_payload(market)
        if record is None:
            session.add(
                PolymarketMarketRecord(
                    market_id=market.market_id,
                    status=market.status,
                    category=market.category,
                    event_slug=market.event_slug,
                    updated_at=market.last_updated_at,
                    payload_json=payload,
                )
            )
        else:
            record.status = market.status
            record.category = market.category
            record.event_slug = market.event_slug
            record.updated_at = market.last_updated_at
            record.payload_json = payload
        return market

    def _list_markets(self, session: Session) -> list[PolymarketMarket]:
        query = select(PolymarketMarketRecord).order_by(PolymarketMarketRecord.updated_at.desc())
        return [self._deserialize_market(record.payload_json) for record in session.scalars(query).all()]

    def _get_market(self, session: Session, market_id: str) -> PolymarketMarket | None:
        record = session.get(PolymarketMarketRecord, market_id)
        return self._deserialize_market(record.payload_json) if record is not None else None

    def _upsert_snapshot(self, session: Session, snapshot: PolymarketOrderBook) -> PolymarketOrderBook:
        snapshot_id = f"pms_{snapshot.market_id}_{int(snapshot.captured_at.timestamp())}"
        record = session.get(PolymarketMarketSnapshotRecord, snapshot_id)
        payload = serialize_payload(snapshot)
        if record is None:
            session.add(
                PolymarketMarketSnapshotRecord(
                    snapshot_id=snapshot_id,
                    market_id=snapshot.market_id,
                    yes_price=snapshot.yes_ask,
                    no_price=snapshot.no_ask,
                    spread_bps=snapshot.spread_bps,
                    captured_at=snapshot.captured_at,
                    payload_json=payload,
                )
            )
        else:
            record.yes_price = snapshot.yes_ask
            record.no_price = snapshot.no_ask
            record.spread_bps = snapshot.spread_bps
            record.captured_at = snapshot.captured_at
            record.payload_json = payload
        return snapshot

    def _upsert_opportunity(self, session: Session, opportunity: PolymarketOpportunity) -> PolymarketOpportunity:
        record = session.get(ArbitrageOpportunityRecord, opportunity.opportunity_id)
        payload = serialize_payload(opportunity)
        if record is None:
            session.add(
                ArbitrageOpportunityRecord(
                    opportunity_id=opportunity.opportunity_id,
                    market="polymarket",
                    symbol_or_market=opportunity.market_id,
                    direction=opportunity.recommended_direction,
                    confidence=opportunity.confidence,
                    status="tradable" if opportunity.tradable else "monitor",
                    detected_at=opportunity.timestamp,
                    payload_json=payload,
                )
            )
        else:
            record.market = "polymarket"
            record.symbol_or_market = opportunity.market_id
            record.direction = opportunity.recommended_direction
            record.confidence = opportunity.confidence
            record.status = "tradable" if opportunity.tradable else "monitor"
            record.detected_at = opportunity.timestamp
            record.payload_json = payload
        return opportunity

    def _list_opportunities(self, session: Session, *, market: str, limit: int) -> list[PolymarketOpportunity]:
        query = (
            select(ArbitrageOpportunityRecord)
            .where(ArbitrageOpportunityRecord.market == market)
            .order_by(ArbitrageOpportunityRecord.detected_at.desc())
            .limit(max(limit, 0))
        )
        return [self._deserialize_opportunity(record.payload_json) for record in session.scalars(query).all()]

    def _get_opportunity(self, session: Session, opportunity_id: str) -> PolymarketOpportunity | None:
        record = session.get(ArbitrageOpportunityRecord, opportunity_id)
        return self._deserialize_opportunity(record.payload_json) if record is not None else None

    def _upsert_validation(self, session: Session, validation: LinkedMarketValidation) -> LinkedMarketValidation:
        record = session.get(LinkedMarketValidationRecord, validation.validation_id)
        payload = serialize_payload(validation)
        if record is None:
            session.add(
                LinkedMarketValidationRecord(
                    validation_id=validation.validation_id,
                    rule_name=validation.rule_name,
                    status=validation.status,
                    detected_at=validation.detected_at,
                    payload_json=payload,
                )
            )
        else:
            record.rule_name = validation.rule_name
            record.status = validation.status
            record.detected_at = validation.detected_at
            record.payload_json = payload
        return validation

    def _deserialize_market(self, payload_json: str) -> PolymarketMarket:
        payload = deserialize_payload(payload_json)
        for field in ("close_time", "last_updated_at"):
            payload[field] = ensure_aware_datetime(payload.get(field))
        return PolymarketMarket(**payload)

    def _deserialize_opportunity(self, payload_json: str) -> PolymarketOpportunity:
        payload = deserialize_payload(payload_json)
        payload["timestamp"] = ensure_aware_datetime(payload.get("timestamp"))
        return PolymarketOpportunity(**payload)

    def _with_session(self, session: Session | None, callback: Callable[[Session], object]) -> object:
        if session is not None:
            return callback(session)
        with self.session_factory.begin() as db:
            return callback(db)

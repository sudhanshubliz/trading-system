from __future__ import annotations

import hashlib
import inspect
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Callable

from app.alpha_fusion.types import AlphaSourceReading
from app.arbitrage.types import BasisFundingOpportunity
from app.config.settings import Settings, get_settings
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.arbitrage_repo import ArbitrageRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.signals.schemas import normalize_requested_symbols


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _zscore(value: float | None, history: list[float]) -> float | None:
    if value is None or len(history) < 3:
        return None
    deviation = pstdev(history)
    if deviation <= 1e-9:
        return 0.0
    return (value - mean(history)) / deviation


class BasisFundingService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        market_data_service: object | None = None,
        arbitrage_repo: ArbitrageRepository | None = None,
        source_repo: AlphaSourcesRepository | None = None,
        events_repo: EventsRepository | None = None,
        time_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.market_data_service = market_data_service
        self.arbitrage_repo = arbitrage_repo
        self.source_repo = source_repo
        self.events_repo = events_repo
        self.time_provider = time_provider or utc_now
        self.supported_symbols = [symbol.upper() for symbol in self.settings.signals_supported_symbols]
        self._history: OrderedDict[str, BasisFundingOpportunity] = OrderedDict()
        self._latest_by_symbol: dict[str, BasisFundingOpportunity] = {}

    async def evaluate_symbol(self, symbol: str, *, generated_at: datetime | None = None) -> BasisFundingOpportunity | None:
        if self.market_data_service is None or symbol.upper() not in self.supported_symbols:
            return None
        symbol = symbol.upper()
        run_time = generated_at or self.time_provider()
        spot_snapshot = await self._maybe_await(getattr(self.market_data_service, "get_snapshot")(symbol))
        funding_snapshot = await self._maybe_await(getattr(self.market_data_service, "get_funding_snapshot")(symbol))
        funding_history = await self._maybe_await(
            getattr(self.market_data_service, "get_funding_history")(symbol, limit=self.settings.basis_history_limit)
        )
        futures_candles = await self._maybe_await(
            getattr(self.market_data_service, "get_futures_candles")(symbol, "1h", limit=self.settings.basis_history_limit)
        )
        spot_candles = await self._maybe_await(getattr(self.market_data_service, "get_candles")(symbol, "1h"))
        order_book = None
        get_order_book = getattr(self.market_data_service, "get_order_book", None)
        if get_order_book is not None:
            order_book = await self._maybe_await(get_order_book(symbol))

        spot_price = getattr(spot_snapshot, "last_price", None) if spot_snapshot is not None else None
        futures_price = funding_snapshot.mark_price if funding_snapshot is not None else None
        basis_bps = None if spot_price in (None, 0) or futures_price is None else ((futures_price - spot_price) / spot_price) * 10000
        basis_history = self._build_basis_history(spot_candles or [], futures_candles or [])
        basis_zscore = _zscore(basis_bps, basis_history)
        funding_values = [item.funding_rate for item in funding_history] if funding_history else []
        funding_value = funding_snapshot.last_funding_rate if funding_snapshot is not None else None
        funding_zscore = _zscore(funding_value, funding_values)

        gross_edge = abs(basis_zscore or 0.0) * 4.0 + abs(funding_zscore or 0.0) * 2.0
        fee_estimate = 4.0
        slippage_estimate = self._estimate_slippage(order_book)
        net_edge = gross_edge - fee_estimate - slippage_estimate
        confidence = min(
            1.0,
            0.35
            + min(abs(basis_zscore or 0.0), 2.0) * 0.18
            + min(abs(funding_zscore or 0.0), 2.0) * 0.12,
        )
        opportunity_type, direction = self._classify_opportunity(
            basis_zscore=basis_zscore,
            funding_value=funding_value,
            funding_zscore=funding_zscore,
        )
        tradable, tradability_reasons = self._check_tradability(
            symbol=symbol,
            net_edge=net_edge,
            order_book=order_book,
            funding_snapshot=funding_snapshot,
            futures_price=futures_price,
            spot_price=spot_price,
        )
        opportunity = BasisFundingOpportunity(
            opportunity_id=self._build_id(symbol, run_time),
            symbol=symbol,
            timestamp=run_time,
            signal_family="basis_funding",
            basis_value=round(basis_bps, 6) if basis_bps is not None else None,
            funding_value=round(funding_value, 8) if funding_value is not None else None,
            basis_zscore=round(basis_zscore, 6) if basis_zscore is not None else None,
            funding_zscore=round(funding_zscore, 6) if funding_zscore is not None else None,
            gross_edge_estimate=round(gross_edge, 6),
            fee_estimate=round(fee_estimate, 6),
            slippage_estimate=round(slippage_estimate, 6),
            net_edge_estimate=round(net_edge, 6),
            confidence=round(confidence, 6),
            recommended_direction=direction,
            expected_holding_period="4h_to_24h",
            explanation=[
                f"Basis={round(basis_bps, 4) if basis_bps is not None else None}bps, funding={funding_value}.",
                f"Basis z-score={round(basis_zscore, 4) if basis_zscore is not None else None}, funding z-score={round(funding_zscore, 4) if funding_zscore is not None else None}.",
                f"Tradable={tradable}; reasons={tradability_reasons or ['passed']}.",
            ],
            opportunity_type=opportunity_type,
            tradable=tradable,
            metadata={
                "annualized_basis_pct": self._annualized_basis_pct(basis_bps),
                "tradability_reasons": tradability_reasons,
                "basis_history_points": len(basis_history),
                "funding_history_points": len(funding_values),
            },
        )
        self._store(opportunity)
        return opportunity

    async def evaluate_symbols(self, symbols: list[str] | None = None) -> list[BasisFundingOpportunity]:
        normalized_symbols = normalize_requested_symbols(symbols) or self.supported_symbols
        items: list[BasisFundingOpportunity] = []
        for symbol in normalized_symbols:
            item = await self.evaluate_symbol(symbol)
            if item is not None:
                items.append(item)
        return items

    def list_opportunities(
        self,
        *,
        symbol: str | None = None,
        tradable: bool | None = None,
        min_confidence: float | None = None,
        recency_seconds: int | None = None,
        limit: int = 100,
    ) -> list[BasisFundingOpportunity]:
        detected_after = self.time_provider() - timedelta(seconds=max(recency_seconds, 0)) if recency_seconds is not None else None
        items = self.arbitrage_repo.list_opportunities(
            symbol=symbol,
            tradable=tradable,
            min_confidence=min_confidence,
            detected_after=detected_after,
            limit=limit,
        ) if self.arbitrage_repo is not None else list(self._history.values())
        filtered = items
        if symbol is not None:
            filtered = [item for item in filtered if item.symbol == symbol.upper()]
        if tradable is not None:
            filtered = [item for item in filtered if item.tradable is tradable]
        if min_confidence is not None:
            filtered = [item for item in filtered if item.confidence >= min_confidence]
        if recency_seconds is not None:
            cutoff = self.time_provider().timestamp() - max(recency_seconds, 0)
            filtered = [item for item in filtered if item.timestamp.timestamp() >= cutoff]
        return filtered[: max(limit, 0)]

    def get_opportunity(self, opportunity_id: str) -> BasisFundingOpportunity | None:
        if self.arbitrage_repo is not None:
            item = self.arbitrage_repo.get_opportunity(opportunity_id)
            if item is not None:
                return item
        return self._history.get(opportunity_id)

    async def as_source_reading(self, symbol: str, *, generated_at: datetime | None = None) -> AlphaSourceReading | None:
        opportunity = await self.evaluate_symbol(symbol, generated_at=generated_at)
        if opportunity is None:
            return None
        return AlphaSourceReading(
            reading_id=f"src_{opportunity.opportunity_id}",
            source_name="basis_funding",
            symbol_or_market=opportunity.symbol,
            direction=opportunity.recommended_direction,
            confidence=opportunity.confidence,
            expected_holding_period=opportunity.expected_holding_period,
            strategy_family="basis_funding",
            raw_signal={
                "basis_value": opportunity.basis_value,
                "funding_value": opportunity.funding_value,
                "opportunity_type": opportunity.opportunity_type,
                "tradable": opportunity.tradable,
            },
            metadata=opportunity.metadata,
            timestamp=opportunity.timestamp,
        )

    async def get_integrity_status(self, symbol: str) -> dict[str, object]:
        opportunity = await self.evaluate_symbol(symbol)
        if opportunity is None:
            return {"healthy": False, "reason": "basis_data_unavailable"}
        reasons = list(opportunity.metadata.get("tradability_reasons", []))
        return {
            "healthy": "data_stale" not in reasons and "missing_prices" not in reasons,
            "reason": ",".join(reasons) if reasons else "ok",
            "timestamp": opportunity.timestamp,
        }

    def _build_basis_history(self, spot_candles: list[object], futures_candles: list[object]) -> list[float]:
        history: list[float] = []
        pairs = zip(spot_candles[-self.settings.basis_history_limit :], futures_candles[-self.settings.basis_history_limit :], strict=False)
        for spot, fut in pairs:
            if spot.close <= 0:
                continue
            history.append(((fut.close - spot.close) / spot.close) * 10000)
        return history

    def _estimate_slippage(self, order_book: object | None) -> float:
        if order_book is None:
            return 4.0
        bids = getattr(order_book, "bids", [])
        asks = getattr(order_book, "asks", [])
        top_depth = sum(level.price * level.quantity for level in list(bids)[:2] + list(asks)[:2])
        if top_depth <= 0:
            return 5.0
        return max(0.5, 15000.0 / top_depth)

    def _classify_opportunity(
        self,
        *,
        basis_zscore: float | None,
        funding_value: float | None,
        funding_zscore: float | None,
    ) -> tuple[str, str]:
        if basis_zscore is None:
            return "none", "neutral"
        if basis_zscore >= self.settings.basis_zscore_action_threshold:
            return "actionable_short_basis_reversion", "short"
        if basis_zscore <= -self.settings.basis_zscore_action_threshold:
            return "actionable_long_basis_reversion", "long"
        if funding_value is not None and funding_value >= self.settings.funding_extreme_pos_threshold:
            return "carry_like_positive", "short"
        if funding_value is not None and funding_value <= self.settings.funding_extreme_neg_threshold:
            return "carry_like_negative", "long"
        if funding_zscore is not None and abs(funding_zscore) >= 1.0:
            return "monitor", "neutral"
        return "none", "neutral"

    def _check_tradability(
        self,
        *,
        symbol: str,
        net_edge: float,
        order_book: object | None,
        funding_snapshot: object | None,
        futures_price: float | None,
        spot_price: float | None,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if net_edge < self.settings.basis_min_net_edge_bps:
            reasons.append("net_edge_below_threshold")
        if spot_price is None or futures_price is None:
            reasons.append("missing_prices")
        if funding_snapshot is None or getattr(funding_snapshot, "fetched_at", None) is None:
            reasons.append("missing_funding_snapshot")
        else:
            age_seconds = (self.time_provider() - funding_snapshot.fetched_at).total_seconds()
            if age_seconds > self.settings.basis_max_data_age_seconds:
                reasons.append("data_stale")
        if order_book is None:
            reasons.append("missing_order_book")
        else:
            total_depth = sum(level.price * level.quantity for level in list(getattr(order_book, "bids", []))[:2] + list(getattr(order_book, "asks", []))[:2])
            if total_depth < self.settings.microstructure_min_depth_usd:
                reasons.append("liquidity_too_thin")
        return len(reasons) == 0, reasons

    def _annualized_basis_pct(self, basis_bps: float | None) -> float | None:
        if basis_bps is None:
            return None
        basis_pct = basis_bps / 100.0
        return basis_pct * 365.0 * 3.0

    def _store(self, opportunity: BasisFundingOpportunity) -> None:
        self._history[opportunity.opportunity_id] = opportunity
        self._history.move_to_end(opportunity.opportunity_id, last=False)
        while len(self._history) > 500:
            self._history.popitem(last=True)
        self._latest_by_symbol[opportunity.symbol] = opportunity
        if self.arbitrage_repo is not None:
            self.arbitrage_repo.upsert_opportunity(opportunity)
        if self.source_repo is not None:
            self.source_repo.upsert_reading(
                AlphaSourceReading(
                    reading_id=f"src_{opportunity.opportunity_id}",
                    source_name="basis_funding",
                    symbol_or_market=opportunity.symbol,
                    direction=opportunity.recommended_direction,
                    confidence=opportunity.confidence,
                    expected_holding_period=opportunity.expected_holding_period,
                    strategy_family="basis_funding",
                    raw_signal={"opportunity_type": opportunity.opportunity_type, "tradable": opportunity.tradable},
                    metadata=opportunity.metadata,
                    timestamp=opportunity.timestamp,
                )
            )
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="basis_funding_opportunity",
                entity_id=opportunity.opportunity_id,
                symbol=opportunity.symbol,
                payload={"tradable": opportunity.tradable, "direction": opportunity.recommended_direction},
            )

    async def _maybe_await(self, value: object) -> object:
        if inspect.isawaitable(value):
            return await value
        return value

    def _build_id(self, symbol: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{symbol}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"arb_{digest[:12]}"

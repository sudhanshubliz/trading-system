from __future__ import annotations

import hashlib
import inspect
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable

from app.alpha_fusion.types import AlphaSourceReading
from app.config.settings import Settings, get_settings
from app.features.microstructure.types import MicrostructureFeatureSnapshot
from app.persistence.repositories.alpha_sources_repo import AlphaSourcesRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.microstructure_repo import MicrostructureRepository
from app.signals.schemas import normalize_requested_symbols


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MicrostructureService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        market_data_service: object | None = None,
        repo: MicrostructureRepository | None = None,
        source_repo: AlphaSourcesRepository | None = None,
        events_repo: EventsRepository | None = None,
        time_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.market_data_service = market_data_service
        self.repo = repo
        self.source_repo = source_repo
        self.events_repo = events_repo
        self.time_provider = time_provider or utc_now
        self.supported_symbols = [symbol.upper() for symbol in self.settings.signals_supported_symbols]
        self._history: OrderedDict[str, MicrostructureFeatureSnapshot] = OrderedDict()
        self._latest_by_symbol: dict[str, MicrostructureFeatureSnapshot] = {}

    async def compute_symbol(self, symbol: str, *, generated_at: datetime | None = None) -> MicrostructureFeatureSnapshot | None:
        if self.market_data_service is None or symbol.upper() not in self.supported_symbols:
            return None
        symbol = symbol.upper()
        run_time = generated_at or self.time_provider()
        get_order_book = getattr(self.market_data_service, "get_order_book", None)
        get_recent_trades = getattr(self.market_data_service, "get_recent_trades", None)
        get_snapshot = getattr(self.market_data_service, "get_snapshot", None)
        if get_order_book is None or get_recent_trades is None or get_snapshot is None:
            return None
        order_book = await self._maybe_await(get_order_book(symbol))
        recent_trades = await self._maybe_await(get_recent_trades(symbol, limit=100))
        ticker_snapshot = await self._maybe_await(get_snapshot(symbol))
        if order_book is None or ticker_snapshot is None:
            return None
        snapshot = self._build_snapshot(symbol=symbol, order_book=order_book, recent_trades=recent_trades, ticker_snapshot=ticker_snapshot, timestamp=run_time)
        self._store(snapshot)
        return snapshot

    async def compute_batch(self, symbols: list[str] | None = None) -> list[MicrostructureFeatureSnapshot]:
        normalized_symbols = normalize_requested_symbols(symbols) or self.supported_symbols
        items: list[MicrostructureFeatureSnapshot] = []
        for symbol in normalized_symbols:
            item = await self.compute_symbol(symbol)
            if item is not None:
                items.append(item)
        return items

    def list_history(self, *, symbol: str | None = None, limit: int = 100) -> list[MicrostructureFeatureSnapshot]:
        if self.repo is not None:
            return self.repo.list_history(symbol=symbol, limit=limit)
        items = list(self._history.values())
        if symbol is not None:
            items = [item for item in items if item.symbol == symbol.upper()]
        return items[: max(limit, 0)]

    def get_latest(self, symbol: str) -> MicrostructureFeatureSnapshot | None:
        if self.repo is not None:
            record = self.repo.get_latest(symbol)
            if record is not None:
                return record
        return self._latest_by_symbol.get(symbol.upper())

    async def as_source_reading(self, symbol: str, *, generated_at: datetime | None = None) -> AlphaSourceReading | None:
        snapshot = await self.compute_symbol(symbol, generated_at=generated_at)
        if snapshot is None:
            return None
        return AlphaSourceReading(
            reading_id=f"src_{snapshot.snapshot_id}",
            source_name="binance_microstructure",
            symbol_or_market=snapshot.symbol,
            direction=snapshot.direction,
            confidence=snapshot.confidence,
            expected_holding_period="seconds_to_minutes",
            strategy_family="binance_microstructure",
            raw_signal={
                "signal_policy": snapshot.signal_policy,
                "market_state": snapshot.market_state,
                "top_n_imbalance": snapshot.top_n_imbalance,
            },
            metadata=snapshot.metadata,
            timestamp=snapshot.timestamp,
        )

    def _build_snapshot(self, *, symbol: str, order_book: object, recent_trades: list[object], ticker_snapshot: object, timestamp: datetime) -> MicrostructureFeatureSnapshot:
        bids = list(getattr(order_book, "bids", []))[: self.settings.microstructure_top_n_levels]
        asks = list(getattr(order_book, "asks", []))[: self.settings.microstructure_top_n_levels]
        best_bid = bids[0].price if bids else getattr(ticker_snapshot, "bid_price", None)
        best_ask = asks[0].price if asks else getattr(ticker_snapshot, "ask_price", None)
        spread_bps = getattr(ticker_snapshot, "spread_bps", None)
        rel_spread = spread_bps
        top_bid_qty = bids[0].quantity if bids else getattr(ticker_snapshot, "best_bid_qty", None)
        top_ask_qty = asks[0].quantity if asks else getattr(ticker_snapshot, "best_ask_qty", None)
        top_level_imbalance = self._imbalance(top_bid_qty, top_ask_qty)
        top_n_bid_qty = sum(level.quantity for level in bids)
        top_n_ask_qty = sum(level.quantity for level in asks)
        top_n_imbalance = self._imbalance(top_n_bid_qty, top_n_ask_qty)
        microprice = None
        if best_bid is not None and best_ask is not None and top_bid_qty is not None and top_ask_qty is not None:
            denom = top_bid_qty + top_ask_qty
            if denom > 0:
                microprice = ((best_ask * top_bid_qty) + (best_bid * top_ask_qty)) / denom
        total_depth_usd = sum(level.price * level.quantity for level in bids + asks)
        depth_concentration = None
        if total_depth_usd > 0:
            top_depth_usd = sum(level.price * level.quantity for level in (bids[:1] + asks[:1]))
            depth_concentration = top_depth_usd / total_depth_usd
        book_slope = None
        if len(bids) >= 2 and len(asks) >= 2:
            bid_span = abs(bids[0].price - bids[-1].price)
            ask_span = abs(asks[-1].price - asks[0].price)
            total_span = bid_span + ask_span
            if total_span > 0:
                book_slope = total_depth_usd / total_span
        stale_book = True
        updated_at = getattr(order_book, "updated_at", None)
        if updated_at is not None:
            stale_book = (timestamp - updated_at).total_seconds() > self.settings.microstructure_stale_book_seconds

        signed_volume = 0.0
        aggressive_buy = 0.0
        aggressive_sell = 0.0
        prices: list[float] = []
        for trade in recent_trades:
            signed = -trade.quantity if trade.is_buyer_maker else trade.quantity
            signed_volume += signed
            prices.append(trade.price)
            if trade.is_buyer_maker:
                aggressive_sell += trade.quantity
            else:
                aggressive_buy += trade.quantity
        trade_flow_imbalance = self._imbalance(aggressive_buy, aggressive_sell)
        trade_intensity = float(len(recent_trades))
        burst_score = min(1.0, trade_intensity / 25.0)
        realized_short_volatility = None
        if len(prices) >= 2:
            returns = [abs((curr - prev) / prev) * 100 for prev, curr in zip(prices, prices[1:], strict=False) if prev > 0]
            if returns:
                realized_short_volatility = sum(returns) / len(returns)
        adverse_selection_proxy = None
        if prices and microprice is not None:
            adverse_selection_proxy = ((prices[-1] - microprice) / microprice) * 10000

        quote_instability_score = min(1.0, getattr(order_book, "update_count_1s", 0) / 15.0)
        depth_depletion = total_depth_usd < self.settings.microstructure_min_depth_usd
        spread_state = "spread_wide" if (rel_spread or 0.0) > self.settings.microstructure_max_relative_spread_bps else "normal"
        liquidity_state = "thin_liquidity" if depth_depletion else "normal"
        if stale_book:
            imbalance_state = "stale_data"
        elif (top_n_imbalance or 0.0) >= self.settings.microstructure_imbalance_threshold:
            imbalance_state = "imbalance_buy_pressure"
        elif (top_n_imbalance or 0.0) <= -self.settings.microstructure_imbalance_threshold:
            imbalance_state = "imbalance_sell_pressure"
        else:
            imbalance_state = "normal"
        volatility_state = "toxic_flow_risk" if (realized_short_volatility or 0.0) >= self.settings.microstructure_vol_shock_threshold else "normal"

        market_state = "normal"
        if stale_book:
            market_state = "stale_data"
        elif spread_state == "spread_wide":
            market_state = "spread_wide"
        elif liquidity_state == "thin_liquidity":
            market_state = "thin_liquidity"
        elif volatility_state == "toxic_flow_risk":
            market_state = "toxic_flow_risk"
        elif quote_instability_score >= 0.8:
            market_state = "unstable_quotes"
        elif imbalance_state == "imbalance_buy_pressure":
            market_state = "imbalance_buy_pressure"
        elif imbalance_state == "imbalance_sell_pressure":
            market_state = "imbalance_sell_pressure"

        signal_policy = "no_trade"
        direction = "neutral"
        confidence = 0.35
        if market_state in {"stale_data", "toxic_flow_risk", "unstable_quotes"}:
            signal_policy = "unsafe_to_trade"
        elif spread_state == "spread_wide" and not depth_depletion:
            signal_policy = "spread_capture_only"
        elif imbalance_state == "imbalance_buy_pressure" and (trade_flow_imbalance or 0.0) > 0.15:
            signal_policy = "taker_buy_momentum"
            direction = "long"
            confidence = 0.68
        elif imbalance_state == "imbalance_sell_pressure" and (trade_flow_imbalance or 0.0) < -0.15:
            signal_policy = "taker_sell_momentum"
            direction = "short"
            confidence = 0.68
        elif imbalance_state == "imbalance_buy_pressure":
            signal_policy = "passive_buy_bias"
            direction = "long"
            confidence = 0.58
        elif imbalance_state == "imbalance_sell_pressure":
            signal_policy = "passive_sell_bias"
            direction = "short"
            confidence = 0.58

        return MicrostructureFeatureSnapshot(
            snapshot_id=self._build_id(symbol, timestamp),
            symbol=symbol,
            timestamp=timestamp,
            top_of_book_spread_bps=round(spread_bps, 6) if spread_bps is not None else None,
            relative_spread_bps=round(rel_spread, 6) if rel_spread is not None else None,
            top_level_imbalance=round(top_level_imbalance, 6) if top_level_imbalance is not None else None,
            top_n_imbalance=round(top_n_imbalance, 6) if top_n_imbalance is not None else None,
            order_book_pressure=round((top_n_imbalance or 0.0) * (1.0 - min((rel_spread or 0.0) / 10.0, 1.0)), 6),
            microprice=round(microprice, 6) if microprice is not None else None,
            book_slope=round(book_slope, 6) if book_slope is not None else None,
            depth_concentration=round(depth_concentration, 6) if depth_concentration is not None else None,
            total_depth_usd=round(total_depth_usd, 6) if total_depth_usd is not None else None,
            depth_depletion_flag=depth_depletion,
            quote_instability_score=round(quote_instability_score, 6),
            trade_flow_imbalance=round(trade_flow_imbalance, 6) if trade_flow_imbalance is not None else None,
            signed_volume=round(signed_volume, 6),
            trade_intensity=round(trade_intensity, 6),
            burst_score=round(burst_score, 6),
            realized_short_volatility=round(realized_short_volatility, 6) if realized_short_volatility is not None else None,
            adverse_selection_proxy=round(adverse_selection_proxy, 6) if adverse_selection_proxy is not None else None,
            stale_book=stale_book,
            spread_state=spread_state,
            liquidity_state=liquidity_state,
            imbalance_state=imbalance_state,
            volatility_state=volatility_state,
            market_state=market_state,
            signal_policy=signal_policy,
            confidence=round(confidence, 6),
            direction=direction,
            explanation=[
                f"Spread={round(rel_spread, 4) if rel_spread is not None else None}bps, depth={round(total_depth_usd, 2) if total_depth_usd is not None else None}.",
                f"Top-N imbalance={round(top_n_imbalance, 4) if top_n_imbalance is not None else None}, trade-flow imbalance={round(trade_flow_imbalance, 4) if trade_flow_imbalance is not None else None}.",
                f"Market state={market_state}, signal policy={signal_policy}.",
            ],
            metadata={
                "update_count_1s": getattr(order_book, "update_count_1s", 0),
                "update_count_5s": getattr(order_book, "update_count_5s", 0),
                "recent_trade_count": len(recent_trades),
            },
        )

    def _store(self, snapshot: MicrostructureFeatureSnapshot) -> None:
        self._history[snapshot.snapshot_id] = snapshot
        self._history.move_to_end(snapshot.snapshot_id, last=False)
        while len(self._history) > 500:
            self._history.popitem(last=True)
        self._latest_by_symbol[snapshot.symbol] = snapshot
        if self.repo is not None:
            self.repo.upsert_snapshot(snapshot)
        if self.source_repo is not None:
            self.source_repo.upsert_reading(
                AlphaSourceReading(
                    reading_id=f"src_{snapshot.snapshot_id}",
                    source_name="binance_microstructure",
                    symbol_or_market=snapshot.symbol,
                    direction=snapshot.direction,
                    confidence=snapshot.confidence,
                    expected_holding_period="seconds_to_minutes",
                    strategy_family="binance_microstructure",
                    raw_signal={"signal_policy": snapshot.signal_policy, "market_state": snapshot.market_state},
                    metadata=snapshot.metadata,
                    timestamp=snapshot.timestamp,
                )
            )
        if self.events_repo is not None:
            self.events_repo.append_event(
                event_type="microstructure_snapshot_generated",
                entity_id=snapshot.snapshot_id,
                symbol=snapshot.symbol,
                payload={"market_state": snapshot.market_state, "signal_policy": snapshot.signal_policy},
            )

    def _imbalance(self, bid: float | None, ask: float | None) -> float | None:
        if bid is None or ask is None:
            return None
        denom = bid + ask
        if denom <= 0:
            return None
        return (bid - ask) / denom

    async def _maybe_await(self, value: object) -> object:
        if inspect.isawaitable(value):
            return await value
        return value

    def _build_id(self, symbol: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{symbol}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()
        return f"mic_{digest[:12]}"

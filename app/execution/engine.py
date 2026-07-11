from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.config.settings import Settings
from app.execution.costs import calculate_fee, calculate_prediction_market_fee
from app.execution.types import Approval, ExecutionResult, Position, Trade
from app.market_data.types import OrderBookLevel, OrderBookSnapshot, TickerSnapshot
from app.risk.types import RiskAssessment


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class PaperFillOutcome:
    fill_price: float
    fill_quantity: float
    partial_fill_ratio: float
    arrival_mid_price: float | None
    expected_price: float
    expected_slippage_bps: float
    realized_slippage_bps: float
    liquidity_used_pct: float
    stale_data_flag: bool
    submit_timestamp: datetime
    fill_timestamp: datetime
    decision_to_order_latency_ms: float
    order_to_fill_latency_ms: float
    total_latency_ms: float
    notes: list[str]


class PaperExecutionEngine:
    def __init__(self, settings: Settings, *, time_provider: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self.time_provider = time_provider or utc_now

    def execute(
        self,
        approval: Approval,
        assessment: RiskAssessment,
        *,
        latest_market_price: float | None,
        snapshot: TickerSnapshot | None,
        order_book: OrderBookSnapshot | None,
        paused: bool,
        provider_health_status: str | None = None,
    ) -> ExecutionResult:
        if approval.status != "approved":
            raise ValueError("approval_not_approved")
        if paused:
            raise ValueError("execution_paused")

        trade_plan = assessment.generated_trade_plan
        requested_entry_price = float(trade_plan.get("entry_price") or 0.0)
        stop_loss = float(trade_plan.get("stop_loss") or 0.0)
        target_1 = float(trade_plan.get("target_1") or 0.0)
        raw_target_2 = trade_plan.get("target_2")
        target_2 = float(raw_target_2) if raw_target_2 is not None else None
        raw_position_size = trade_plan.get("position_size")
        quantity = float(raw_position_size) if raw_position_size is not None else 0.0
        if requested_entry_price <= 0 or stop_loss <= 0 or target_1 <= 0 or quantity <= 0:
            raise ValueError("invalid_trade_plan")

        now = self.time_provider()
        fill = self._simulate_fill(
            symbol=approval.symbol,
            side=approval.side,
            requested_quantity=quantity,
            requested_entry_price=requested_entry_price,
            latest_market_price=latest_market_price,
            snapshot=snapshot,
            order_book=order_book,
            decision_timestamp=approval.approved_at or now,
            now=now,
        )

        trade_id = self._build_id("trd", approval.approval_id)
        position_id = self._build_id("pos", trade_id)
        entry_notional = fill.fill_price * fill.fill_quantity
        fee_model = str(trade_plan.get("fee_model") or "fixed_bps")
        fee_rate = float(trade_plan.get("fee_rate") or 0.0)
        entry_fee = (
            self._calculate_entry_fee(
                fee_model=fee_model,
                fee_rate=fee_rate,
                shares=fill.fill_quantity,
                price=fill.fill_price,
                notional=entry_notional,
            )
            if self.settings.execution_mode in {"paper", "shadow"}
            else 0.0
        )
        entry_slippage_cost = abs(fill.fill_price - fill.expected_price) * fill.fill_quantity

        trade = Trade(
            trade_id=trade_id,
            approval_id=approval.approval_id,
            assessment_id=approval.assessment_id,
            signal_id=approval.signal_id,
            position_id=position_id,
            symbol=approval.symbol,
            side=approval.side,
            strategy_name=approval.strategy_name,
            quantity=fill.fill_quantity,
            execution_price=fill.fill_price,
            requested_entry_price=requested_entry_price,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            status="executed",
            execution_mode=self.settings.execution_mode,
            opened_at=fill.fill_timestamp,
            updated_at=fill.fill_timestamp,
            realized_pnl=round(-entry_fee, 6),
            gross_realized_pnl=0.0,
            fees_paid=round(entry_fee, 6),
            slippage_cost=round(entry_slippage_cost, 6),
            failure_reason=None,
            fee_model=fee_model,
            fee_rate=fee_rate,
        )

        position = Position(
            position_id=position_id,
            trade_id=trade_id,
            approval_id=approval.approval_id,
            assessment_id=approval.assessment_id,
            signal_id=approval.signal_id,
            symbol=approval.symbol,
            side=approval.side,
            strategy_name=approval.strategy_name,
            initial_quantity=fill.fill_quantity,
            quantity_open=fill.fill_quantity,
            entry_price=fill.fill_price,
            current_price=fill.fill_price,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            status="open",
            opened_at=fill.fill_timestamp,
            updated_at=fill.fill_timestamp,
            realized_pnl=round(-entry_fee, 6),
            gross_realized_pnl=0.0,
            fees_paid=round(entry_fee, 6),
            slippage_cost=round(entry_slippage_cost, 6),
            execution_mode=self.settings.execution_mode,
            fee_model=fee_model,
            fee_rate=fee_rate,
        )

        return ExecutionResult(
            approval=replace(approval),
            trade=trade,
            position=position,
            execution_details={
                "decision_to_order_latency_ms": fill.decision_to_order_latency_ms,
                "order_to_fill_latency_ms": fill.order_to_fill_latency_ms,
                "total_latency_ms": fill.total_latency_ms,
                "submit_timestamp": fill.submit_timestamp,
                "fill_timestamp": fill.fill_timestamp,
                "expected_price": fill.expected_price,
                "arrival_mid_price": fill.arrival_mid_price,
                "simulated_fill_price": fill.fill_price,
                "expected_slippage_bps": fill.expected_slippage_bps,
                "slippage_bps": fill.realized_slippage_bps,
                "realized_slippage_bps": fill.realized_slippage_bps,
                "liquidity_used_pct": fill.liquidity_used_pct,
                "partial_fill_ratio": fill.partial_fill_ratio,
                "stale_data_flag": fill.stale_data_flag,
                "provider_health_at_execution": provider_health_status,
                "entry_fee": round(entry_fee, 6),
                "entry_slippage_cost": round(entry_slippage_cost, 6),
                "fee_bps": self.settings.paper_execution_fee_bps if fee_model == "fixed_bps" else None,
                "fee_model": fee_model,
                "fee_rate": fee_rate,
                "notes": fill.notes,
            },
        )

    def _simulate_fill(
        self,
        *,
        symbol: str,
        side: str,
        requested_quantity: float,
        requested_entry_price: float,
        latest_market_price: float | None,
        snapshot: TickerSnapshot | None,
        order_book: OrderBookSnapshot | None,
        decision_timestamp: datetime,
        now: datetime,
    ) -> PaperFillOutcome:
        stale_data_flag = self._is_stale(
            symbol=symbol,
            snapshot=snapshot,
            order_book=order_book,
            now=now,
        )
        if stale_data_flag and self.settings.stale_market_data_blocks_trading:
            raise ValueError("stale_market_data")

        best_bid = snapshot.bid_price if snapshot is not None else None
        best_ask = snapshot.ask_price if snapshot is not None else None
        if order_book is not None and order_book.bids and order_book.asks:
            best_bid = order_book.bids[0].price
            best_ask = order_book.asks[0].price

        reference_price = self._resolve_price(latest_market_price, requested_entry_price)
        arrival_mid = None
        if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask > 0:
            arrival_mid = (best_bid + best_ask) / 2.0
        elif snapshot is not None and snapshot.last_price is not None:
            arrival_mid = snapshot.last_price
        elif reference_price > 0:
            arrival_mid = reference_price

        side_value = side.lower()
        fill_levels = self._levels_for_side(side_value, order_book, best_bid=best_bid, best_ask=best_ask, reference_price=reference_price)
        fill_price, fill_quantity, depth_notional = self._walk_book(fill_levels, requested_quantity)
        if fill_quantity <= 0:
            raise ValueError("no_fill_available")

        partial_fill_ratio = max(0.0, min(1.0, fill_quantity / requested_quantity))
        if partial_fill_ratio < max(self.settings.paper_execution_min_fill_ratio, 0.05):
            raise ValueError("insufficient_depth")

        expected_price = arrival_mid or requested_entry_price or reference_price
        spread_bps = snapshot.spread_bps if snapshot is not None and snapshot.spread_bps is not None else self._derived_spread_bps(best_bid, best_ask)
        expected_slippage_bps = max(
            self.settings.paper_execution_base_slippage_bps,
            (spread_bps or self.settings.paper_execution_base_slippage_bps) * self.settings.paper_execution_spread_weight,
        )
        visible_depth_notional = sum(level.price * level.quantity for level in fill_levels)
        requested_notional = requested_quantity * max(expected_price, 1e-9)
        liquidity_used_pct = min(1.0, requested_notional / max(visible_depth_notional, 1e-9))
        expected_slippage_bps += liquidity_used_pct * self.settings.paper_execution_depth_penalty_bps

        decision_to_order_latency_ms = float(self.settings.execution_sim_latency_ms)
        order_to_fill_latency_ms = float(
            self.settings.paper_execution_fill_latency_ms
            + (liquidity_used_pct * self.settings.paper_execution_latency_depth_penalty_ms)
        )
        total_latency_ms = decision_to_order_latency_ms + order_to_fill_latency_ms
        submit_timestamp = decision_timestamp + timedelta(milliseconds=decision_to_order_latency_ms)
        fill_timestamp = submit_timestamp + timedelta(milliseconds=order_to_fill_latency_ms)

        adverse_selection_bps = min(
            self.settings.paper_execution_adverse_selection_bps,
            (total_latency_ms / 1000.0) * self.settings.paper_execution_latency_adverse_selection_bps_per_sec,
        )
        if spread_bps is not None and spread_bps > self.settings.microstructure_max_relative_spread_bps:
            adverse_selection_bps += min(spread_bps * 0.2, 25.0)

        adjusted_fill_price = self._apply_bps(fill_price, adverse_selection_bps, side=side_value)
        realized_slippage_bps = abs((adjusted_fill_price - expected_price) / max(expected_price, 1e-9)) * 10000.0
        notes = [
            f"depth_notional={round(depth_notional, 6)}",
            f"liquidity_used_pct={round(liquidity_used_pct, 6)}",
            f"fees_bps={round(self.settings.paper_execution_fee_bps, 6)}",
        ]
        if partial_fill_ratio < 1.0:
            notes.append("partial_fill_applied")
        if stale_data_flag:
            notes.append("stale_data_observed")

        return PaperFillOutcome(
            fill_price=round(adjusted_fill_price, 6),
            fill_quantity=round(fill_quantity, self.settings.position_size_precision),
            partial_fill_ratio=round(partial_fill_ratio, 6),
            arrival_mid_price=round(arrival_mid, 6) if arrival_mid is not None else None,
            expected_price=round(expected_price, 6),
            expected_slippage_bps=round(expected_slippage_bps, 6),
            realized_slippage_bps=round(realized_slippage_bps, 6),
            liquidity_used_pct=round(liquidity_used_pct, 6),
            stale_data_flag=stale_data_flag,
            submit_timestamp=submit_timestamp,
            fill_timestamp=fill_timestamp,
            decision_to_order_latency_ms=round(decision_to_order_latency_ms, 6),
            order_to_fill_latency_ms=round(order_to_fill_latency_ms, 6),
            total_latency_ms=round(total_latency_ms, 6),
            notes=notes,
        )

    def _levels_for_side(
        self,
        side: str,
        order_book: OrderBookSnapshot | None,
        *,
        best_bid: float | None,
        best_ask: float | None,
        reference_price: float,
    ) -> list[OrderBookLevel]:
        if order_book is not None:
            if side == "long" and order_book.asks:
                return list(order_book.asks[: self.settings.paper_execution_max_book_levels])
            if side == "short" and order_book.bids:
                return list(order_book.bids[: self.settings.paper_execution_max_book_levels])
        synthetic_spread_bps = max(self.settings.paper_execution_base_spread_bps, 1.0)
        if best_bid is None or best_ask is None:
            mid = reference_price
            best_bid = mid * (1 - synthetic_spread_bps / 20000)
            best_ask = mid * (1 + synthetic_spread_bps / 20000)
        level_qty = max(self.settings.paper_execution_synthetic_depth_usd / max(reference_price, 1e-9), 0.0001)
        if side == "long":
            return [OrderBookLevel(price=best_ask, quantity=level_qty)]
        return [OrderBookLevel(price=best_bid, quantity=level_qty)]

    def _walk_book(self, levels: list[OrderBookLevel], requested_quantity: float) -> tuple[float, float, float]:
        remaining = requested_quantity
        consumed_qty = 0.0
        consumed_notional = 0.0
        visible_depth_notional = 0.0
        for level in levels:
            visible_depth_notional += level.price * level.quantity
            if remaining <= 0:
                continue
            take_qty = min(level.quantity, remaining)
            consumed_qty += take_qty
            consumed_notional += take_qty * level.price
            remaining -= take_qty
        if consumed_qty <= 0:
            return 0.0, 0.0, visible_depth_notional
        return consumed_notional / consumed_qty, consumed_qty, visible_depth_notional

    def _is_stale(
        self,
        *,
        symbol: str,
        snapshot: TickerSnapshot | None,
        order_book: OrderBookSnapshot | None,
        now: datetime,
    ) -> bool:
        if symbol.upper().startswith("PM_"):
            stale_cutoff_ticker = timedelta(seconds=max(self.settings.latency_arb_max_data_age_sec, 1))
            stale_cutoff_book = stale_cutoff_ticker
        else:
            stale_cutoff_ticker = timedelta(milliseconds=self.settings.market_data_ticker_freshness_ms)
            stale_cutoff_book = timedelta(seconds=max(self.settings.microstructure_stale_book_seconds, 1))
        snapshot_ts = snapshot.snapshot_time or snapshot.ticker_updated_at if snapshot is not None else None
        orderbook_ts = order_book.updated_at if order_book is not None else (snapshot.orderbook_updated_at if snapshot is not None else None)
        snapshot_stale = snapshot_ts is None or now - snapshot_ts > stale_cutoff_ticker
        orderbook_stale = orderbook_ts is None or now - orderbook_ts > stale_cutoff_book
        return snapshot_stale or orderbook_stale

    def _calculate_entry_fee(
        self,
        *,
        fee_model: str,
        fee_rate: float,
        shares: float,
        price: float,
        notional: float,
    ) -> float:
        if fee_model == "polymarket_probability":
            return calculate_prediction_market_fee(shares=shares, price=price, fee_rate=fee_rate)
        return calculate_fee(notional, self.settings.paper_execution_fee_bps)

    def _resolve_price(self, latest_market_price: float | None, fallback_entry_price: float) -> float:
        if latest_market_price is not None and latest_market_price > 0:
            return latest_market_price
        return fallback_entry_price

    def _derived_spread_bps(self, bid: float | None, ask: float | None) -> float | None:
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None
        mid = (bid + ask) / 2.0
        if mid <= 0:
            return None
        return ((ask - bid) / mid) * 10000.0

    def _apply_bps(self, price: float, bps: float, *, side: str) -> float:
        if side == "long":
            return price * (1 + (bps / 10000.0))
        return price * (1 - (bps / 10000.0))

    def _build_id(self, prefix: str, value: str) -> str:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
        return f"{prefix}_{digest[:12]}"

from __future__ import annotations

import hashlib
import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.arbitrage.service import BasisFundingService
from app.execution.service import ExecutionService
from app.execution_quality.service import ExecutionQualityService
from app.features.microstructure.service import MicrostructureService
from app.market_data.types import (
    Candle,
    FundingRatePoint,
    FundingSnapshot,
    OrderBookLevel,
    OrderBookSnapshot,
    TickerSnapshot,
    TradePrint,
)
from app.replay.loader import slice_replay_candles
from app.replay.metrics import build_replay_metrics
from app.replay.timeframes import candle_close_time
from app.replay.types import EquityPoint, ReplayFidelityMetadata, ReplayRun, ReplayRunConfig, ReplayTradeResult
from app.risk.locks import RiskLockManager
from app.risk.service import RiskService
from app.signals.service import SignalService
from app.strategy_owner.service import StrategyOwnerService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


class ReplayClock:
    def __init__(self) -> None:
        self.current_time = utc_now()

    def set(self, timestamp: datetime) -> None:
        self.current_time = timestamp

    def now(self) -> datetime:
        return self.current_time


class ReplayMarketDataService:
    def __init__(
        self,
        candles: dict[str, dict[str, list[Candle]]],
        futures_candles: dict[str, dict[str, list[Candle]]],
        trigger_timeframe: str,
        history_limit: int = 300,
    ) -> None:
        self._candles = candles
        self._futures_candles = futures_candles
        self._trigger_timeframe = trigger_timeframe.lower()
        self._history_limit = max(history_limit, 1)
        self._close_timestamps_by_series_id = {
            id(series): [candle_close_time(candle.open_time, timeframe) for candle in series]
            for store in (candles, futures_candles)
            for timeframes in store.values()
            for timeframe, series in timeframes.items()
        }
        self._current_time: datetime | None = None

    def set_time(self, timestamp: datetime) -> None:
        self._current_time = timestamp

    async def get_health(self) -> dict[str, str]:
        return {"status": "ok" if self._current_time is not None else "degraded"}

    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        return self._visible_series(symbol, timeframe, futures=False)

    async def get_futures_candles(self, symbol: str, timeframe: str, limit: int | None = None) -> list[Candle]:
        series = self._visible_series(symbol, timeframe, futures=True)
        if limit is not None and limit > 0:
            return series[-limit:]
        return series

    async def get_snapshot(self, symbol: str) -> TickerSnapshot:
        latest = self._latest_candle_with_timeframe(symbol, preferred=("5m", self._trigger_timeframe))
        if latest is None:
            return TickerSnapshot(symbol=symbol.upper(), last_price=None)
        timeframe, candle = latest
        updated_at = candle_close_time(candle.open_time, timeframe)
        spread_bps = self._spread_bps(candle)
        bid_price = candle.close * (1 - spread_bps / 20000)
        ask_price = candle.close * (1 + spread_bps / 20000)
        depth_notional = self._depth_notional(candle)
        bid_qty = (depth_notional / 2) / max(bid_price, 1e-9)
        ask_qty = (depth_notional / 2) / max(ask_price, 1e-9)
        return TickerSnapshot(
            symbol=symbol.upper(),
            last_price=round(candle.close, 6),
            bid_price=round(bid_price, 6),
            ask_price=round(ask_price, 6),
            best_bid_qty=round(bid_qty, 6),
            best_ask_qty=round(ask_qty, 6),
            spread_bps=round(spread_bps, 6),
            volume_24h=round(candle.volume * 24.0, 6),
            ws_status="ok",
            rest_status="ok",
            fallback_active=False,
            ticker_updated_at=updated_at,
            orderbook_updated_at=updated_at,
            snapshot_time=self._current_time,
        )

    async def get_order_book(self, symbol: str) -> OrderBookSnapshot | None:
        latest = self._latest_candle_with_timeframe(symbol, preferred=("5m", self._trigger_timeframe))
        if latest is None:
            return None
        timeframe, candle = latest
        spread_bps = self._spread_bps(candle)
        bias = max(-0.25, min(0.25, (candle.close - candle.open) / max(candle.open, 1e-9) * 8.0))
        bid_multiplier = 1.0 + max(bias, 0.0)
        ask_multiplier = 1.0 + max(-bias, 0.0)
        levels = 5
        depth_notional = self._depth_notional(candle)
        bids: list[OrderBookLevel] = []
        asks: list[OrderBookLevel] = []
        for level in range(levels):
            distance_bps = spread_bps / 2 + level * max(spread_bps, 0.6)
            bid_price = candle.close * (1 - distance_bps / 10000)
            ask_price = candle.close * (1 + distance_bps / 10000)
            level_notional = depth_notional / (levels * 2) * (1 + (levels - level) / levels * 0.3)
            bids.append(
                OrderBookLevel(
                    price=round(bid_price, 6),
                    quantity=round((level_notional * bid_multiplier) / max(bid_price, 1e-9), 6),
                )
            )
            asks.append(
                OrderBookLevel(
                    price=round(ask_price, 6),
                    quantity=round((level_notional * ask_multiplier) / max(ask_price, 1e-9), 6),
                )
            )
        update_rate = max(1, min(8, int(candle.volume / 40)))
        return OrderBookSnapshot(
            symbol=symbol.upper(),
            bids=bids,
            asks=asks,
            updated_at=candle_close_time(candle.open_time, timeframe),
            update_count_1s=update_rate,
            update_count_5s=update_rate * 4,
        )

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[TradePrint]:
        candle = self._latest_candle(symbol, preferred=("5m", self._trigger_timeframe))
        if candle is None:
            return []
        count = max(8, min(limit, int(candle.volume / 8) if candle.volume > 0 else 8))
        base_qty = max(candle.volume / max(count, 1), 0.0001)
        direction_up = candle.close >= candle.open
        trades: list[TradePrint] = []
        for index in range(count):
            progress = index / max(count - 1, 1)
            arc = math.sin(progress * math.pi)
            price = candle.open + (candle.close - candle.open) * progress + ((candle.close - candle.open) * 0.1 * arc)
            if direction_up:
                is_buyer_maker = index % 5 == 0
            else:
                is_buyer_maker = index % 5 != 0
            trades.append(
                TradePrint(
                    symbol=symbol.upper(),
                    price=round(price, 6),
                    quantity=round(base_qty * (1 + (index % 3) * 0.15), 6),
                    is_buyer_maker=is_buyer_maker,
                    trade_time=candle.open_time + timedelta(seconds=index),
                )
            )
        return trades[-limit:]

    async def get_funding_snapshot(self, symbol: str) -> FundingSnapshot | None:
        spot_latest = self._latest_candle_with_timeframe(symbol, preferred=("1h", self._trigger_timeframe))
        futures_latest = self._latest_candle_with_timeframe(
            symbol,
            preferred=("1h", self._trigger_timeframe),
            futures=True,
        )
        if spot_latest is None or futures_latest is None:
            return None
        spot_timeframe, spot_candle = spot_latest
        futures_timeframe, futures_candle = futures_latest
        rate = self._funding_rate_from_pair(spot_candle, futures_candle)
        observed_at = min(
            candle_close_time(spot_candle.open_time, spot_timeframe),
            candle_close_time(futures_candle.open_time, futures_timeframe),
        )
        return FundingSnapshot(
            symbol=symbol.upper(),
            mark_price=round(futures_candle.close, 6),
            index_price=round(spot_candle.close, 6),
            last_funding_rate=round(rate, 8),
            next_funding_time=(self._current_time or futures_candle.open_time) + timedelta(hours=8),
            fetched_at=observed_at,
        )

    async def get_funding_history(self, symbol: str, limit: int = 50) -> list[FundingRatePoint]:
        spot_history = self._visible_series(symbol, "1h", futures=False)
        futures_history = self._visible_series(symbol, "1h", futures=True)
        pairs = list(zip(spot_history, futures_history, strict=False))[-max(limit, 0) :]
        items: list[FundingRatePoint] = []
        for spot_candle, futures_candle in pairs:
            items.append(
                FundingRatePoint(
                    symbol=symbol.upper(),
                    funding_rate=round(self._funding_rate_from_pair(spot_candle, futures_candle), 8),
                    funding_time=candle_close_time(futures_candle.open_time, "1h"),
                    mark_price=round(futures_candle.close, 6),
                )
            )
        return items

    def _visible_series(self, symbol: str, timeframe: str, *, futures: bool) -> list[Candle]:
        all_candles = self._all_series(symbol, timeframe, futures=futures)
        if self._current_time is None:
            return []
        timestamps = self._close_timestamps_by_series_id.get(id(all_candles))
        if timestamps is None:
            timestamps = [candle_close_time(candle.open_time, timeframe) for candle in all_candles]
            self._close_timestamps_by_series_id[id(all_candles)] = timestamps
        visible_end = bisect_right(timestamps, self._current_time)
        visible_start = max(0, visible_end - self._history_limit)
        return [candle for candle in all_candles[visible_start:visible_end] if candle.is_closed]

    def _all_series(self, symbol: str, timeframe: str, *, futures: bool) -> list[Candle]:
        store = self._futures_candles if futures else self._candles
        series = store.get(symbol.upper(), {}).get(timeframe.lower(), [])
        if series:
            return series
        if futures:
            return self._candles.get(symbol.upper(), {}).get(timeframe.lower(), [])
        return []

    def _latest_candle(self, symbol: str, *, preferred: tuple[str, ...]) -> Candle | None:
        latest = self._latest_candle_with_timeframe(symbol, preferred=preferred)
        return latest[1] if latest is not None else None

    def _latest_candle_with_timeframe(
        self,
        symbol: str,
        *,
        preferred: tuple[str, ...],
        futures: bool = False,
    ) -> tuple[str, Candle] | None:
        for timeframe in preferred:
            series = self._visible_series(symbol, timeframe, futures=futures)
            if series:
                return timeframe, series[-1]
        return None

    def _latest_futures_candle(self, symbol: str, *, preferred: tuple[str, ...]) -> Candle | None:
        latest = self._latest_candle_with_timeframe(symbol, preferred=preferred, futures=True)
        return latest[1] if latest is not None else None

    def _spread_bps(self, candle: Candle) -> float:
        range_pct = abs(candle.high - candle.low) / max(candle.close, 1e-9)
        return max(0.6, min(4.0, range_pct * 300))

    def _depth_notional(self, candle: Candle) -> float:
        return max(8000.0, candle.close * max(candle.volume, 1.0) * 0.12)

    def _funding_rate_from_pair(self, spot_candle: Candle, futures_candle: Candle) -> float:
        if spot_candle.close <= 0:
            return 0.0
        basis_bps = ((futures_candle.close - spot_candle.close) / spot_candle.close) * 10000
        drift = ((futures_candle.close - futures_candle.open) / max(futures_candle.open, 1e-9)) * 0.0002
        return max(-0.002, min(0.002, basis_bps / 100000 + drift))


class ReplayEngine:
    def __init__(self, settings) -> None:
        self.settings = settings

    async def run(self, config: ReplayRunConfig) -> ReplayRun:
        started_at = utc_now()
        run_id = self._build_run_id(config)
        replay_candles = slice_replay_candles(
            config.candles,
            symbols=config.symbols,
            start_time=config.start_time,
            end_time=config.end_time,
            max_bars=config.max_bars,
        )
        replay_futures_candles = slice_replay_candles(
            config.futures_candles or {},
            symbols=config.symbols,
            start_time=config.start_time,
            end_time=config.end_time,
            max_bars=config.max_bars,
        )

        clock = ReplayClock()
        local_settings = self.settings.model_copy(update=self._build_settings_overrides(config))
        replay_market_data = ReplayMarketDataService(
            replay_candles,
            replay_futures_candles,
            self.settings.signals_trigger_timeframe,
            history_limit=local_settings.market_data_candle_limit,
        )
        signal_service = SignalService(
            settings=local_settings,
            market_data_service=replay_market_data,
            time_provider=clock.now,
        )
        arbitrage_service = BasisFundingService(
            settings=local_settings,
            market_data_service=replay_market_data,
            time_provider=clock.now,
        )
        microstructure_service = MicrostructureService(
            settings=local_settings,
            market_data_service=replay_market_data,
            time_provider=clock.now,
        )
        execution_quality_service = ExecutionQualityService(settings=local_settings)
        risk_lock_manager = RiskLockManager(time_provider=clock.now)
        risk_service = RiskService(
            settings=local_settings,
            signal_service=signal_service,
            market_data_service=replay_market_data,
            time_provider=clock.now,
            risk_lock_manager=risk_lock_manager,
            execution_quality_service=execution_quality_service,
            arbitrage_service=arbitrage_service,
            microstructure_service=microstructure_service,
        )
        execution_service = ExecutionService(
            settings=local_settings,
            risk_service=risk_service,
            market_data_service=replay_market_data,
            time_provider=clock.now,
            use_persistent_control_state=False,
            execution_quality_service=execution_quality_service,
        )
        strategy_owner_service = StrategyOwnerService(
            settings=local_settings,
            signal_service=signal_service,
            arbitrage_service=arbitrage_service,
            microstructure_service=microstructure_service,
            market_data_service=replay_market_data,
            execution_quality_service=execution_quality_service,
            risk_service=risk_service,
            time_provider=clock.now,
        )

        events = self._build_events(replay_candles, config.symbols)
        equity_curve: list[EquityPoint] = []
        basis_artifacts: list[dict[str, object]] = []
        microstructure_artifacts: list[dict[str, object]] = []
        risk_rejections: list[dict[str, object]] = []
        strategy_owner_artifacts: list[dict[str, object]] = []

        for timestamp, symbols_at_step in events:
            clock.set(timestamp)
            replay_market_data.set_time(timestamp)

            basis_items = await arbitrage_service.evaluate_symbols(list(symbols_at_step))
            microstructure_items = await microstructure_service.compute_batch(list(symbols_at_step))
            basis_artifacts.extend(_serialize(basis_items))
            microstructure_artifacts.extend(_serialize(microstructure_items))

            await execution_service.sync_positions_with_market()

            open_positions = await execution_service.get_positions()
            open_keys = {
                (position.symbol, position.strategy_name)
                for position in open_positions
                if position.status != "closed"
            }
            traded_this_candle: set[tuple[str, str]] = set()

            evaluation = await strategy_owner_service.evaluate(symbols=list(symbols_at_step))
            strategy_owner_artifacts.extend(
                [
                    {
                        "candidate_id": decision.candidate_id,
                        "status": decision.status,
                        "strategy_family": decision.strategy_family,
                        "symbol_or_market": decision.symbol_or_market,
                        "rejection_reason": decision.rejection_reason,
                        "timestamp": decision.timestamp,
                    }
                    for decision in evaluation.decisions
                ]
            )
            candidate_by_id = {candidate.candidate_id: candidate for candidate in evaluation.candidates}
            for decision in evaluation.decisions:
                if decision.status != "accepted_for_risk" or decision.risk_assessment_id is None:
                    if decision.status in {"rejected", "rejected_by_risk"}:
                        risk_rejections.append(
                            {
                                "signal_id": decision.candidate_id,
                                "symbol": decision.symbol_or_market,
                                "decision": decision.status,
                                "rejection_reasons": [decision.rejection_reason] if decision.rejection_reason else [],
                                "active_risk_locks": [],
                                "timestamp": timestamp,
                            }
                        )
                    continue
                candidate = candidate_by_id.get(decision.candidate_id)
                if candidate is None:
                    risk_service.release_assessment_reservation(decision.risk_assessment_id)
                    continue
                key = (candidate.symbol_or_market, candidate.strategy_name or candidate.strategy_family)
                if key in open_keys or key in traded_this_candle:
                    risk_service.release_assessment_reservation(decision.risk_assessment_id)
                    continue
                assessment = risk_service.get_assessment(decision.risk_assessment_id)
                if assessment is None or assessment.final_decision != "approved_for_review":
                    risk_service.release_assessment_reservation(decision.risk_assessment_id)
                    continue
                approval = await execution_service.create_approval_from_assessment(assessment.assessment_id)
                try:
                    await execution_service.approve_and_execute(approval.approval_id)
                except ValueError:
                    risk_service.release_assessment_reservation(assessment.assessment_id)
                    risk_rejections.append(
                        {
                            "signal_id": assessment.signal_id,
                            "symbol": assessment.symbol,
                            "decision": "execution_blocked",
                            "rejection_reasons": ["execution_blocked"],
                            "active_risk_locks": _serialize(risk_service.list_current_locks()),
                            "timestamp": timestamp,
                        }
                    )
                    continue
                traded_this_candle.add(key)
                open_keys.add(key)

            pnl = await execution_service.get_pnl_summary()
            equity_curve.append(
                EquityPoint(
                    timestamp=timestamp,
                    equity=round(config.initial_balance + pnl.realized_pnl_total + pnl.unrealized_pnl_total, 4),
                    realized_pnl=round(pnl.realized_pnl_total, 4),
                    unrealized_pnl=round(pnl.unrealized_pnl_total, 4),
                )
            )

        if events:
            clock.set(events[-1][0])
            replay_market_data.set_time(events[-1][0])

        await execution_service.close_open_positions("end_of_replay")
        pnl = await execution_service.get_pnl_summary()
        if events:
            equity_curve.append(
                EquityPoint(
                    timestamp=clock.now(),
                    equity=round(config.initial_balance + pnl.realized_pnl_total + pnl.unrealized_pnl_total, 4),
                    realized_pnl=round(pnl.realized_pnl_total, 4),
                    unrealized_pnl=round(pnl.unrealized_pnl_total, 4),
                )
            )

        positions = await execution_service.get_positions()
        trades = await execution_service.get_trades()
        trade_results = self._build_trade_results(trades, positions)
        metrics = build_replay_metrics(
            initial_balance=config.initial_balance,
            trades=trade_results,
            equity_curve=equity_curve,
        )

        completed_at = clock.now() if events else started_at
        prediction_market_artifacts, fidelity_metadata = self._build_prediction_market_artifacts(
            run_id=run_id,
            config=config,
            completed_at=completed_at,
        )
        phase2_artifacts = {
            "basis_funding_opportunities": basis_artifacts,
            "microstructure_snapshots": microstructure_artifacts,
            "strategy_owner_decisions": strategy_owner_artifacts,
            "risk_rejections": risk_rejections,
            "execution_quality_records": _serialize(execution_quality_service.list_records(limit=500)),
            "risk_lock_events": _serialize(risk_lock_manager.list_history(limit=500)),
            "active_risk_locks_at_end": _serialize(risk_service.list_current_locks()),
            "prediction_market_replay": prediction_market_artifacts,
            "summary": {
                "basis_opportunity_count": len(basis_artifacts),
                "microstructure_snapshot_count": len(microstructure_artifacts),
                "strategy_owner_decision_count": len(strategy_owner_artifacts),
                "risk_rejection_count": len(risk_rejections),
                "execution_quality_count": len(execution_quality_service.list_records(limit=500)),
                "risk_lock_event_count": len(risk_lock_manager.list_history(limit=500)),
                "active_risk_lock_count_at_end": len(risk_service.list_current_locks()),
                "polymarket_snapshot_count": len(config.polymarket_snapshots),
                "event_observation_count": len(config.event_observations),
                "wallet_observation_count": len(config.wallet_observations),
            },
        }
        fidelity_notes = [
            "Completed candle OHLC values become visible only at the interval close boundary to prevent bar-level lookahead.",
            "Replay microstructure uses deterministic synthetic order-book and tape features derived from candle paths and volume.",
            "Replay funding and basis use futures-vs-spot candle approximations when historical funding snapshots are unavailable.",
            "Execution quality in replay reflects simulated fills against replay snapshots, not exchange-confirmed venue latency or queue position.",
        ]
        fidelity_notes.extend(fidelity_metadata.notes)
        return ReplayRun(
            run_id=run_id,
            status="completed",
            symbols=config.symbols,
            initial_balance=config.initial_balance,
            total_steps=len(events),
            started_at=started_at,
            completed_at=completed_at,
            trades=trade_results,
            metrics=metrics,
            phase2_artifacts=phase2_artifacts,
            fidelity_notes=fidelity_notes,
            fidelity_mode=config.fidelity_mode,
            fidelity_metadata=fidelity_metadata,
        )

    def _build_events(
        self,
        candles: dict[str, dict[str, list[Candle]]],
        symbols: list[str],
    ) -> list[tuple[datetime, set[str]]]:
        grouped: dict[datetime, set[str]] = defaultdict(set)
        trigger_timeframe = self.settings.signals_trigger_timeframe.lower()
        for symbol in symbols:
            trigger_candles = candles.get(symbol.upper(), {}).get(trigger_timeframe, [])
            for candle in trigger_candles:
                if candle.is_closed:
                    grouped[candle_close_time(candle.open_time, trigger_timeframe)].add(symbol.upper())
        return sorted(grouped.items(), key=lambda item: item[0])

    def _build_trade_results(
        self,
        trades: list[object],
        positions: list[object],
    ) -> list[ReplayTradeResult]:
        positions_by_trade_id = {position.trade_id: position for position in positions}
        results: list[ReplayTradeResult] = []
        for trade in trades:
            position = positions_by_trade_id.get(trade.trade_id)
            if position is None:
                continue
            results.append(
                ReplayTradeResult(
                    trade_id=trade.trade_id,
                    position_id=position.position_id,
                    symbol=trade.symbol,
                    side=trade.side,
                    strategy_name=trade.strategy_name,
                    entry_price=trade.execution_price,
                    exit_price=position.current_price,
                    quantity=trade.quantity,
                    opened_at=trade.opened_at,
                    closed_at=trade.closed_at,
                    realized_pnl=round(position.realized_pnl, 4),
                    exit_reason=position.close_reason,
                    status=trade.status,
                    gross_realized_pnl=round(position.gross_realized_pnl, 4),
                    fees_paid=round(position.fees_paid, 4),
                    slippage_cost=round(position.slippage_cost, 4),
                )
            )
        results.sort(key=lambda item: item.opened_at)
        return results

    def _build_run_id(self, config: ReplayRunConfig) -> str:
        strategy_part = ",".join(f"{key}={config.strategy_overrides[key]}" for key in sorted(config.strategy_overrides))
        risk_part = ",".join(f"{key}={config.risk_overrides[key]}" for key in sorted(config.risk_overrides))
        seed = "|".join(
            [
                ",".join(sorted(config.symbols)),
                str(config.initial_balance),
                str(sum(len(timeframes.get(self.settings.signals_trigger_timeframe.lower(), [])) for timeframes in config.candles.values())),
                str(sum(len(timeframes.get("1h", [])) for timeframes in config.futures_candles.values())),
                config.start_time.isoformat() if config.start_time is not None else "",
                config.end_time.isoformat() if config.end_time is not None else "",
                str(config.max_bars or ""),
                strategy_part,
                risk_part,
            ]
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        return f"rpl_{digest[:12]}"

    def _build_settings_overrides(self, config: ReplayRunConfig) -> dict[str, int | float]:
        overrides: dict[str, int | float] = {
            "paper_account_start_balance": config.initial_balance,
        }
        overrides.update(config.strategy_overrides)
        overrides.update(config.risk_overrides)
        return overrides

    def _build_prediction_market_artifacts(
        self,
        *,
        run_id: str,
        config: ReplayRunConfig,
        completed_at: datetime,
    ) -> tuple[dict[str, object], ReplayFidelityMetadata]:
        polymarket_candidates = []
        for snapshot in config.polymarket_snapshots:
            yes_price = float(snapshot.get("yes_price", 0.0) or 0.0)
            no_price = float(snapshot.get("no_price", 0.0) or 0.0)
            deviation = (yes_price + no_price) - 1.0
            if abs(deviation) >= 0.03:
                polymarket_candidates.append(
                    {
                        "market_id": snapshot.get("market_id"),
                        "yes_plus_no": round(yes_price + no_price, 6),
                        "deviation_from_one": round(deviation, 6),
                        "signal_type": "yes_no_sum_dislocation",
                    }
                )

        event_candidates = []
        for observation in config.event_observations:
            importance = float(observation.get("importance_score", 0.0) or 0.0)
            relevance = float(observation.get("relevance_score", 0.0) or 0.0)
            if importance >= self.settings.event_min_importance_score and relevance >= self.settings.event_min_relevance_score:
                event_candidates.append(
                    {
                        "event_id": observation.get("event_id"),
                        "entities": observation.get("entities", []),
                        "importance_score": round(importance, 6),
                        "relevance_score": round(relevance, 6),
                    }
                )

        wallet_candidates = []
        for observation in config.wallet_observations:
            conviction = float(observation.get("conviction", observation.get("inferred_conviction", 0.0)) or 0.0)
            if conviction >= 0.55:
                wallet_candidates.append(
                    {
                        "wallet_id": observation.get("wallet_id"),
                        "market": observation.get("market") or observation.get("market_or_symbol"),
                        "conviction": round(conviction, 6),
                    }
                )

        precision_claim = {
            "low_fidelity": "coarse_snapshot_replay",
            "medium": "snapshot_and_annotation_replay",
            "high_fidelity_best_effort": "best_effort_snapshot_reconstruction",
        }.get(config.fidelity_mode, "snapshot_and_annotation_replay")
        notes = [
            f"Replay fidelity mode={config.fidelity_mode}.",
            "Prediction-market replay uses stored snapshots and annotations, not venue-level queue reconstruction.",
        ]
        if config.fidelity_mode == "low_fidelity":
            notes.append("Low fidelity only evaluates snapshot-level dislocations and event annotations.")
        elif config.fidelity_mode == "high_fidelity_best_effort":
            notes.append("High-fidelity best effort includes all available snapshots but still avoids claiming order-by-order precision.")
        if not config.allow_partial_external_data and (
            not config.polymarket_snapshots or not config.event_observations or not config.wallet_observations
        ):
            notes.append("Replay requested full external coverage, but one or more external datasets were missing.")

        metadata = ReplayFidelityMetadata(
            run_id=run_id,
            fidelity_mode=config.fidelity_mode,
            external_dataset_summary={
                "polymarket_snapshots": len(config.polymarket_snapshots),
                "event_observations": len(config.event_observations),
                "wallet_observations": len(config.wallet_observations),
                "polymarket_signal_candidates": len(polymarket_candidates),
                "event_signal_candidates": len(event_candidates),
                "wallet_signal_candidates": len(wallet_candidates),
            },
            precision_claim=precision_claim,
            notes=notes,
            generated_at=completed_at,
        )
        return (
            {
                "polymarket_signal_candidates": polymarket_candidates,
                "event_signal_candidates": event_candidates,
                "wallet_signal_candidates": wallet_candidates,
                "fidelity_mode": config.fidelity_mode,
                "allow_partial_external_data": config.allow_partial_external_data,
            },
            metadata,
        )

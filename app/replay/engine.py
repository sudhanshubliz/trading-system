from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone

from app.config.settings import Settings
from app.execution.service import ExecutionService
from app.market_data.types import Candle
from app.replay.loader import slice_replay_candles
from app.replay.metrics import build_replay_metrics
from app.replay.types import EquityPoint, ReplayRun, ReplayRunConfig, ReplayTradeResult
from app.risk.service import RiskService
from app.signals.service import SignalService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReplayClock:
    def __init__(self) -> None:
        self.current_time = utc_now()

    def set(self, timestamp: datetime) -> None:
        self.current_time = timestamp

    def now(self) -> datetime:
        return self.current_time


class ReplayMarketDataService:
    def __init__(self, candles: dict[str, dict[str, list[Candle]]], trigger_timeframe: str) -> None:
        self._candles = candles
        self._trigger_timeframe = trigger_timeframe.lower()
        self._current_time: datetime | None = None

    def set_time(self, timestamp: datetime) -> None:
        self._current_time = timestamp

    async def get_health(self) -> dict[str, str]:
        return {"status": "ok"}

    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        all_candles = self._candles.get(symbol.upper(), {}).get(timeframe.lower(), [])
        if self._current_time is None:
            return []
        return [candle for candle in all_candles if candle.is_closed and candle.open_time <= self._current_time]

    async def get_snapshot(self, symbol: str) -> dict[str, float | None]:
        candles = await self.get_candles(symbol, self._trigger_timeframe)
        if not candles:
            return {"last_price": None}
        return {"last_price": candles[-1].close}


class ReplayEngine:
    def __init__(self, settings: Settings) -> None:
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

        clock = ReplayClock()
        replay_market_data = ReplayMarketDataService(
            replay_candles,
            self.settings.signals_trigger_timeframe,
        )
        local_settings = self.settings.model_copy(update=self._build_settings_overrides(config))
        signal_service = SignalService(
            settings=local_settings,
            market_data_service=replay_market_data,
            time_provider=clock.now,
        )
        risk_service = RiskService(
            settings=local_settings,
            signal_service=signal_service,
            market_data_service=replay_market_data,
            time_provider=clock.now,
        )
        execution_service = ExecutionService(
            settings=local_settings,
            risk_service=risk_service,
            market_data_service=replay_market_data,
            time_provider=clock.now,
            use_persistent_control_state=False,
        )

        events = self._build_events(replay_candles, config.symbols)
        equity_curve: list[EquityPoint] = []

        for timestamp, symbols_at_step in events:
            clock.set(timestamp)
            replay_market_data.set_time(timestamp)

            await execution_service.sync_positions_with_market()

            open_positions = await execution_service.get_positions()
            open_keys = {
                (position.symbol, position.strategy_name)
                for position in open_positions
                if position.status != "closed"
            }
            traded_this_candle: set[tuple[str, str]] = set()

            signals = await signal_service.evaluate_symbols(
                list(symbols_at_step),
                generated_at=timestamp,
            )
            for signal in signals:
                key = (signal.symbol, signal.strategy_name)
                if key in open_keys or key in traded_this_candle:
                    continue

                assessment = await risk_service.validate_signal_payload(signal)
                if assessment.final_decision != "approved_for_review":
                    continue

                approval = await execution_service.create_approval_from_assessment(assessment.assessment_id)
                try:
                    await execution_service.approve_and_execute(approval.approval_id)
                except ValueError:
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
                    grouped[candle.open_time].add(symbol.upper())
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

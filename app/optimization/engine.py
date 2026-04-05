from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

from app.config.settings import Settings
from app.optimization.grid import build_parameter_grid
from app.optimization.types import (
    OptimizationCandidateConfig,
    OptimizationParameterGrid,
    OptimizationResultRow,
    OptimizationRunResult,
    WalkForwardFoldResult,
)
from app.replay.loader import slice_replay_candles
from app.replay.service import ReplayService
from app.replay.types import ReplayRun, ReplayTradeResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OptimizationEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run(
        self,
        *,
        candles: dict,
        symbols: list[str],
        initial_balance: float,
        parameter_grid: OptimizationParameterGrid,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        max_bars: int | None = None,
        walk_forward_splits: int | None = None,
    ) -> OptimizationRunResult:
        started_at = utc_now()
        notes: list[str] = []
        selected_symbols = [symbol.upper() for symbol in symbols]
        candidates = build_parameter_grid(parameter_grid, self.settings.optimization_max_combinations)
        run_id = self._build_run_id(
            symbols=selected_symbols,
            initial_balance=initial_balance,
            candidate_count=len(candidates),
            start_time=start_time,
            end_time=end_time,
            max_bars=max_bars,
        )

        if not candidates:
            return OptimizationRunResult(
                run_id=run_id,
                status="empty",
                symbols=selected_symbols,
                started_at=started_at,
                completed_at=started_at,
                total_combinations=0,
                evaluated_combinations=0,
                leaderboard=[],
                notes=["no valid parameter combinations"],
            )

        replay_candles = slice_replay_candles(
            candles,
            symbols=selected_symbols,
            start_time=start_time,
            end_time=end_time,
            max_bars=max_bars,
        )
        if not any(series for timeframes in replay_candles.values() for series in timeframes.values()):
            return OptimizationRunResult(
                run_id=run_id,
                status="empty",
                symbols=selected_symbols,
                started_at=started_at,
                completed_at=started_at,
                total_combinations=len(candidates),
                evaluated_combinations=0,
                leaderboard=[],
                notes=["insufficient data"],
            )

        fold_windows = self._build_fold_windows(
            candles=replay_candles,
            symbols=selected_symbols,
            requested_splits=walk_forward_splits or self.settings.optimization_walk_forward_splits,
        )
        requested_splits = walk_forward_splits or self.settings.optimization_walk_forward_splits
        if fold_windows and len(fold_windows) < requested_splits:
            notes.append(f"walk-forward reduced to {len(fold_windows)} folds")

        leaderboard: list[OptimizationResultRow] = []
        for candidate in candidates:
            row = await self._evaluate_candidate(
                candidate=candidate,
                candles=replay_candles,
                symbols=selected_symbols,
                initial_balance=initial_balance,
                fold_windows=fold_windows,
            )
            leaderboard.append(row)

        ranked = self._rank_rows(leaderboard)
        completed_at = utc_now()
        return OptimizationRunResult(
            run_id=run_id,
            status="completed" if ranked else "empty",
            symbols=selected_symbols,
            started_at=started_at,
            completed_at=completed_at,
            total_combinations=len(candidates),
            evaluated_combinations=len(leaderboard),
            leaderboard=ranked,
            notes=notes,
        )

    async def _evaluate_candidate(
        self,
        *,
        candidate: OptimizationCandidateConfig,
        candles: dict,
        symbols: list[str],
        initial_balance: float,
        fold_windows: list[tuple[datetime | None, datetime | None, datetime | None, datetime | None]],
    ) -> OptimizationResultRow:
        replay_service = ReplayService(settings=self.settings)
        strategy_overrides = {
            "ema_fast_period": candidate.ema_fast_period,
            "ema_slow_period": candidate.ema_slow_period,
            "rsi_period": candidate.rsi_period,
            "breakout_lookback": candidate.breakout_lookback,
        }
        risk_overrides = {
            "min_confidence_score": candidate.min_confidence_score,
            "min_reward_risk_ratio": candidate.min_reward_risk_ratio,
        }
        full_run = await replay_service.run_replay(
            candles_source=candles,
            symbols=symbols,
            initial_balance=initial_balance,
            strategy_overrides=strategy_overrides,
            risk_overrides=risk_overrides,
        )

        walk_forward_results: list[WalkForwardFoldResult] = []
        for fold_index, (train_start, train_end, test_start, test_end) in enumerate(fold_windows, start=1):
            fold_run = await replay_service.run_replay(
                candles_source=candles,
                symbols=symbols,
                initial_balance=initial_balance,
                strategy_overrides=strategy_overrides,
                risk_overrides=risk_overrides,
                start_time=test_start,
                end_time=test_end,
            )
            fold_metrics = fold_run.metrics
            walk_forward_results.append(
                WalkForwardFoldResult(
                    fold_index=fold_index,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    metrics={
                        "total_trades": int(fold_metrics.total_trades if fold_metrics is not None else 0),
                        "net_pnl": self._safe_number(
                            fold_metrics.realized_pnl_total if fold_metrics is not None else 0.0
                        ),
                        "win_rate": self._safe_number(fold_metrics.win_rate if fold_metrics is not None else 0.0),
                        "profit_factor": self._safe_number(
                            fold_metrics.profit_factor if fold_metrics is not None else 0.0
                        ),
                        "max_drawdown_pct": self._safe_number(
                            fold_metrics.max_drawdown_pct if fold_metrics is not None else 0.0
                        ),
                        "expectancy": self._safe_number(
                            fold_metrics.expectancy if fold_metrics is not None else 0.0
                        ),
                    },
                )
            )

        metrics = full_run.metrics
        total_trades = int(metrics.total_trades if metrics is not None else 0)
        win_rate = self._safe_number(metrics.win_rate if metrics is not None else 0.0)
        net_pnl = self._safe_number(metrics.realized_pnl_total if metrics is not None else 0.0)
        expectancy = self._safe_number(metrics.expectancy if metrics is not None else 0.0)
        profit_factor = self._safe_number(metrics.profit_factor if metrics is not None else 0.0)
        max_drawdown_pct = self._safe_number(metrics.max_drawdown_pct if metrics is not None else 0.0)
        average_hold_minutes = self._calculate_average_hold_minutes(full_run.trades)

        passed_guardrails, guardrail_failures = self._evaluate_guardrails(
            total_trades=total_trades,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            walk_forward_results=walk_forward_results,
        )
        robustness_score = self._calculate_robustness_score(
            expectancy=expectancy,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            win_rate=win_rate,
            walk_forward_results=walk_forward_results,
            passed_guardrails=passed_guardrails,
        )

        return OptimizationResultRow(
            config_id=candidate.config_id,
            parameters={
                "ema_fast_period": candidate.ema_fast_period,
                "ema_slow_period": candidate.ema_slow_period,
                "rsi_period": candidate.rsi_period,
                "breakout_lookback": candidate.breakout_lookback,
                "min_confidence_score": candidate.min_confidence_score,
                "min_reward_risk_ratio": candidate.min_reward_risk_ratio,
            },
            total_trades=total_trades,
            win_rate=win_rate,
            net_pnl=net_pnl,
            expectancy=expectancy,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            average_hold_minutes=average_hold_minutes,
            robustness_score=robustness_score,
            passed_guardrails=passed_guardrails,
            guardrail_failures=guardrail_failures,
            walk_forward_results=walk_forward_results,
        )

    def _build_fold_windows(
        self,
        *,
        candles: dict,
        symbols: list[str],
        requested_splits: int,
    ) -> list[tuple[datetime | None, datetime | None, datetime | None, datetime | None]]:
        if requested_splits <= 0:
            return []

        trigger_timeframe = self.settings.signals_trigger_timeframe.lower()
        timestamps = sorted(
            {
                candle.open_time
                for symbol in symbols
                for candle in candles.get(symbol.upper(), {}).get(trigger_timeframe, [])
                if candle.is_closed
            }
        )
        if not timestamps:
            return []

        actual_splits = min(requested_splits, len(timestamps))
        fold_windows: list[tuple[datetime | None, datetime | None, datetime | None, datetime | None]] = []
        for index in range(actual_splits):
            start_idx = (len(timestamps) * index) // actual_splits
            end_idx = (len(timestamps) * (index + 1)) // actual_splits
            if start_idx >= end_idx:
                continue
            test_start = timestamps[start_idx]
            test_end = timestamps[end_idx - 1]
            train_start = timestamps[0] if index > 0 else None
            train_end = timestamps[start_idx - 1] if index > 0 and start_idx > 0 else None
            fold_windows.append((train_start, train_end, test_start, test_end))
        return fold_windows

    def _evaluate_guardrails(
        self,
        *,
        total_trades: int,
        profit_factor: float,
        max_drawdown_pct: float,
        walk_forward_results: list[WalkForwardFoldResult],
    ) -> tuple[bool, list[str]]:
        failures: list[str] = []
        if total_trades < self.settings.optimization_min_trades:
            failures.append("minimum_trades_not_met")
        if profit_factor < self.settings.optimization_min_profit_factor:
            failures.append("profit_factor_below_minimum")
        if max_drawdown_pct > self.settings.optimization_max_drawdown_pct:
            failures.append("max_drawdown_exceeded")

        if self.settings.optimization_require_walk_forward:
            if not walk_forward_results:
                failures.append("walk_forward_missing")
            else:
                non_negative_folds = sum(
                    1 for fold in walk_forward_results if self._safe_number(fold.metrics.get("net_pnl", 0.0)) >= 0
                )
                required = max(1, math.ceil(len(walk_forward_results) / 2))
                if non_negative_folds < required:
                    failures.append("walk_forward_instability")

        return (len(failures) == 0, failures)

    def _calculate_robustness_score(
        self,
        *,
        expectancy: float,
        profit_factor: float,
        max_drawdown_pct: float,
        win_rate: float,
        walk_forward_results: list[WalkForwardFoldResult],
        passed_guardrails: bool,
    ) -> float:
        expectancy_norm = self._clamp((expectancy + 50.0) / 100.0)
        profit_factor_norm = self._clamp(profit_factor / 3.0)
        drawdown_norm = self._clamp(1.0 - (max_drawdown_pct / 100.0))
        win_rate_norm = self._clamp(win_rate / 100.0)
        if walk_forward_results:
            stable_folds = sum(
                1 for fold in walk_forward_results if self._safe_number(fold.metrics.get("net_pnl", 0.0)) >= 0
            )
            stability_norm = self._clamp(stable_folds / len(walk_forward_results))
        else:
            stability_norm = 0.0

        raw_score = (
            (expectancy_norm * 0.20)
            + (profit_factor_norm * 0.25)
            + (drawdown_norm * 0.20)
            + (win_rate_norm * 0.15)
            + (stability_norm * 0.20)
        ) * 100.0
        if not passed_guardrails:
            raw_score *= 0.4
        return round(self._clamp(raw_score / 100.0) * 100.0, 4)

    def _calculate_average_hold_minutes(self, trades: list[ReplayTradeResult]) -> float:
        hold_minutes: list[float] = []
        for trade in trades:
            if trade.closed_at is None:
                continue
            delta = trade.closed_at - trade.opened_at
            hold_minutes.append(max(delta.total_seconds() / 60.0, 0.0))
        if not hold_minutes:
            return 0.0
        return round(sum(hold_minutes) / len(hold_minutes), 4)

    def _rank_rows(self, rows: list[OptimizationResultRow]) -> list[OptimizationResultRow]:
        return sorted(
            rows,
            key=lambda row: (
                not row.passed_guardrails,
                -row.robustness_score,
                -row.net_pnl,
            ),
        )

    def _build_run_id(
        self,
        *,
        symbols: list[str],
        initial_balance: float,
        candidate_count: int,
        start_time: datetime | None,
        end_time: datetime | None,
        max_bars: int | None,
    ) -> str:
        seed = "|".join(
            [
                ",".join(sorted(symbols)),
                str(initial_balance),
                str(candidate_count),
                start_time.isoformat() if start_time is not None else "",
                end_time.isoformat() if end_time is not None else "",
                str(max_bars or ""),
            ]
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        return f"opt_{digest[:12]}"

    def _safe_number(self, value: float | int) -> float:
        numeric = float(value)
        if not math.isfinite(numeric):
            return 0.0
        return round(numeric, 4)

    def _clamp(self, value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        if not math.isfinite(value):
            return minimum
        return max(minimum, min(maximum, value))

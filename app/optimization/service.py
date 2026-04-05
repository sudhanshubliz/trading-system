from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from app.config.settings import Settings, get_settings
from app.optimization.engine import OptimizationEngine
from app.optimization.types import OptimizationParameterGrid, OptimizationResultRow, OptimizationRunResult
from app.persistence.repositories.optimization_repo import OptimizationRepository
from app.replay.loader import load_candles_from_file


class OptimizationService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        optimization_repo: OptimizationRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.engine = OptimizationEngine(self.settings)
        self.optimization_repo = optimization_repo
        self._runs: OrderedDict[str, OptimizationRunResult] = OrderedDict()

    async def stop(self) -> None:
        return None

    async def run_optimization(self, request: Any) -> OptimizationRunResult:
        data = request.model_dump() if hasattr(request, "model_dump") else dict(request)
        candles = self._load_data_files(data.get("data_files") or {})
        grid = self._build_parameter_grid(data.get("parameter_grid") or {})
        symbols = [symbol.upper() for symbol in (data.get("symbols") or self.settings.optimization_default_symbols)]
        initial_balance = float(data.get("initial_balance") or self.settings.optimization_default_initial_balance)

        run = await self.engine.run(
            candles=candles,
            symbols=symbols,
            initial_balance=initial_balance,
            parameter_grid=grid,
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            max_bars=data.get("max_bars"),
            walk_forward_splits=data.get("walk_forward_splits"),
        )
        self._runs[run.run_id] = run
        self._runs.move_to_end(run.run_id, last=False)
        while len(self._runs) > self.settings.optimization_store_limit:
            self._runs.popitem(last=True)
        if self.optimization_repo is not None:
            self.optimization_repo.upsert_optimization_run(run)
        return run

    def list_runs(self) -> list[OptimizationRunResult]:
        if not self._runs and self.optimization_repo is not None:
            for run in self.optimization_repo.list_runs():
                self._runs[run.run_id] = run
        return list(self._runs.values())

    def get_run(self, run_id: str) -> OptimizationRunResult | None:
        run = self._runs.get(run_id)
        if run is None and self.optimization_repo is not None:
            run = self.optimization_repo.get_optimization_run(run_id)
            if run is not None:
                self._runs[run.run_id] = run
        return run

    def get_leaderboard(self, run_id: str, top_n: int | None = None) -> list[OptimizationResultRow] | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        if top_n is None:
            return run.leaderboard
        return run.leaderboard[: max(top_n, 0)]

    def _build_parameter_grid(self, payload: dict[str, list[int | float]]) -> OptimizationParameterGrid:
        return OptimizationParameterGrid(
            ema_fast_periods=[int(value) for value in payload.get("ema_fast_periods", [])],
            ema_slow_periods=[int(value) for value in payload.get("ema_slow_periods", [])],
            rsi_periods=[int(value) for value in payload.get("rsi_periods", [])],
            breakout_lookbacks=[int(value) for value in payload.get("breakout_lookbacks", [])],
            min_confidence_scores=[int(value) for value in payload.get("min_confidence_scores", [])],
            min_reward_risk_ratios=[float(value) for value in payload.get("min_reward_risk_ratios", [])],
        )

    def _load_data_files(self, data_files: dict[str, dict[str, str]]) -> dict[str, dict[str, list]]:
        candles: dict[str, dict[str, list]] = {}
        for symbol, timeframe_paths in data_files.items():
            normalized_symbol = str(symbol).upper()
            candles[normalized_symbol] = {}
            for timeframe, raw_path in timeframe_paths.items():
                path = Path(raw_path)
                candles[normalized_symbol][str(timeframe).lower()] = load_candles_from_file(path)
        return candles

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime

from app.config.settings import Settings, get_settings
from app.persistence.repositories.replay_repo import ReplayRepository
from app.replay.engine import ReplayEngine
from app.replay.loader import load_replay_candles
from app.replay.types import ReplayRun, ReplayRunConfig, WalkForwardReplayReport
from app.replay.walk_forward import build_walk_forward_report


class ReplayService:
    def __init__(self, settings: Settings | None = None, *, replay_repo: ReplayRepository | None = None) -> None:
        self.settings = settings or get_settings()
        self.engine = ReplayEngine(self.settings)
        self.replay_repo = replay_repo
        self._runs: OrderedDict[str, ReplayRun] = OrderedDict()

    async def stop(self) -> None:
        return None

    async def run_replay(
        self,
        *,
        candles_source: str | dict | list,
        futures_candles_source: dict | list | None = None,
        symbols: list[str] | None = None,
        initial_balance: float | None = None,
        strategy_overrides: dict[str, int | float] | None = None,
        risk_overrides: dict[str, int | float] | None = None,
        start_time=None,
        end_time=None,
        max_bars: int | None = None,
        fidelity_mode: str | None = None,
        allow_partial_external_data: bool | None = None,
        polymarket_snapshots: list[dict[str, object]] | None = None,
        event_observations: list[dict[str, object]] | None = None,
        wallet_observations: list[dict[str, object]] | None = None,
    ) -> ReplayRun:
        candles = load_replay_candles(candles_source)
        resolved_symbols = [symbol.upper() for symbol in symbols] if symbols else sorted(candles.keys())
        config = ReplayRunConfig(
            symbols=resolved_symbols,
            initial_balance=initial_balance or self.settings.paper_account_start_balance,
            candles=candles,
            futures_candles=load_replay_candles(futures_candles_source) if futures_candles_source else {},
            strategy_overrides=strategy_overrides or {},
            risk_overrides=risk_overrides or {},
            start_time=start_time,
            end_time=end_time,
            max_bars=max_bars,
            fidelity_mode=fidelity_mode or self.settings.replay_default_fidelity,
            allow_partial_external_data=(
                self.settings.replay_allow_partial_external_data
                if allow_partial_external_data is None
                else allow_partial_external_data
            ),
            polymarket_snapshots=polymarket_snapshots or [],
            event_observations=event_observations or [],
            wallet_observations=wallet_observations or [],
        )
        run = await self.engine.run(config)
        self._runs[run.run_id] = run
        self._runs.move_to_end(run.run_id, last=False)
        while len(self._runs) > 50:
            self._runs.popitem(last=True)
        if self.replay_repo is not None:
            self.replay_repo.upsert_replay_run(run)
        return run

    async def run_walk_forward(
        self,
        *,
        candles_source: str | dict | list,
        futures_candles_source: dict | list | None = None,
        symbols: list[str] | None = None,
        initial_balance: float | None = None,
        start_time: datetime,
        end_time: datetime,
        fold_count: int | None = None,
        fidelity_mode: str | None = None,
    ) -> tuple[ReplayRun, WalkForwardReplayReport]:
        run = await self.run_replay(
            candles_source=candles_source,
            futures_candles_source=futures_candles_source,
            symbols=symbols,
            initial_balance=initial_balance,
            start_time=start_time,
            end_time=end_time,
            fidelity_mode=fidelity_mode,
        )
        report = build_walk_forward_report(
            run,
            start_time=start_time,
            end_time=end_time,
            fold_count=fold_count or self.settings.replay_walk_forward_folds,
            minimum_days=self.settings.replay_walk_forward_min_days,
            minimum_trades=self.settings.optimization_min_trades,
            minimum_profit_factor=self.settings.optimization_min_profit_factor,
            maximum_drawdown_pct=self.settings.optimization_max_drawdown_pct,
        )
        run.phase2_artifacts["walk_forward"] = asdict(report)
        if self.replay_repo is not None:
            self.replay_repo.upsert_replay_run(run)
        return run, report

    def list_runs(self) -> list[ReplayRun]:
        if not self._runs and self.replay_repo is not None:
            for run in self.replay_repo.list_runs():
                self._runs[run.run_id] = run
        return list(self._runs.values())

    def get_run(self, run_id: str) -> ReplayRun | None:
        run = self._runs.get(run_id)
        if run is None and self.replay_repo is not None:
            run = self.replay_repo.get_replay_run(run_id)
            if run is not None:
                self._runs[run.run_id] = run
        return run

    def get_metrics(self, run_id: str):
        run = self._runs.get(run_id)
        if run is None:
            return None
        return run.metrics

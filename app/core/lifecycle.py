from __future__ import annotations

import logging

from fastapi import FastAPI

from app.analytics.service import AnalyticsService
from app.config.settings import get_settings
from app.db.session import init_db
from app.execution.live_adapter import BinanceLiveExecutionAdapter
from app.execution.live_sync import LiveSyncService
from app.execution.service import ExecutionService
from app.live.controller import LiveController
from app.live.locks import LiveLockManager
from app.live.rollout import LiveRolloutPolicy
from app.live.reconciler import LiveReconciler
from app.market_data.service import MarketDataService
from app.ops.recovery import RecoveryService
from app.ops.startup_checks import StartupCheckService
from app.ops.status import OpsService
from app.optimization.service import OptimizationService
from app.persistence.db import get_persistence_session_factory, init_persistence_db
from app.persistence.repositories.approvals_repo import ApprovalsRepository
from app.persistence.repositories.analytics_repo import AnalyticsRepository
from app.persistence.repositories.events_repo import EventsRepository
from app.persistence.repositories.optimization_repo import OptimizationRepository
from app.persistence.repositories.portfolio_repo import PortfolioRepository
from app.persistence.repositories.positions_repo import PositionsRepository
from app.persistence.repositories.replay_repo import ReplayRepository
from app.persistence.repositories.reports_repo import ReportsRepository
from app.persistence.repositories.risk_repo import RiskRepository
from app.persistence.repositories.rollout_repo import RolloutRepository
from app.persistence.repositories.signals_repo import SignalsRepository
from app.persistence.repositories.trades_repo import TradesRepository
from app.persistence.repositories.locks_repo import LocksRepository
from app.portfolio.service import PortfolioService
from app.reporting.aggregator import ReportAggregator
from app.reporting.service import ReportingService
from app.replay.service import ReplayService
from app.risk.service import RiskService
from app.shadow.runner import ShadowRunner
from app.shadow.service import ShadowService
from app.signals.service import SignalService

logger = logging.getLogger(__name__)


async def startup(app: FastAPI) -> None:
    settings = get_settings()
    init_db()
    app.state.market_data_service = None
    app.state.signal_service = None
    app.state.risk_service = None
    app.state.execution_service = None
    app.state.replay_service = None
    app.state.optimization_service = None
    app.state.reporting_service = None
    app.state.shadow_service = None
    app.state.live_controller = None
    app.state.rollout_service = None
    app.state.portfolio_service = None
    app.state.analytics_service = None
    app.state.startup_check_service = None
    app.state.startup_report = None
    app.state.recovery_service = None
    app.state.recovery_report = None
    app.state.ops_service = None
    app.state.persistence_ready = False
    app.state.persistence_error = None

    logger.info(
        "application startup service=%s version=%s env=%s",
        settings.app_name,
        settings.app_version,
        settings.app_env,
    )

    persistence_repos = {
        "signals_repo": None,
        "risk_repo": None,
        "approvals_repo": None,
        "trades_repo": None,
        "positions_repo": None,
        "replay_repo": None,
        "optimization_repo": None,
        "reports_repo": None,
        "events_repo": None,
        "locks_repo": None,
        "rollout_repo": None,
        "portfolio_repo": None,
        "analytics_repo": None,
        "session_factory": None,
    }
    if settings.persistence_enabled:
        try:
            init_persistence_db(settings)
            session_factory = get_persistence_session_factory(settings.persistence_db_url)
            persistence_repos = {
                "signals_repo": SignalsRepository(session_factory),
                "risk_repo": RiskRepository(session_factory),
                "approvals_repo": ApprovalsRepository(session_factory),
                "trades_repo": TradesRepository(session_factory),
                "positions_repo": PositionsRepository(session_factory),
                "replay_repo": ReplayRepository(session_factory),
                "optimization_repo": OptimizationRepository(session_factory),
                "reports_repo": ReportsRepository(session_factory),
                "events_repo": EventsRepository(session_factory),
                "locks_repo": LocksRepository(session_factory),
                "rollout_repo": RolloutRepository(session_factory),
                "portfolio_repo": PortfolioRepository(session_factory),
                "analytics_repo": AnalyticsRepository(session_factory),
                "session_factory": session_factory,
            }
            app.state.persistence_ready = True
        except Exception as exc:
            logger.exception("persistence bootstrap failed")
            app.state.persistence_error = str(exc)
    else:
        app.state.persistence_error = "persistence_disabled"

    if settings.market_data_enabled:
        service = MarketDataService(settings=settings)
        app.state.market_data_service = service

        try:
            await service.start()
        except Exception:
            logger.exception("market data service failed to start")
    else:
        logger.info("market data service disabled")

    if settings.signals_enabled:
        app.state.signal_service = SignalService(
            settings=settings,
            market_data_service=app.state.market_data_service,
            signals_repo=persistence_repos.get("signals_repo"),
            events_repo=persistence_repos.get("events_repo"),
        )
    else:
        logger.info("signal service disabled")

    if settings.risk_engine_enabled:
        app.state.risk_service = RiskService(
            settings=settings,
            signal_service=app.state.signal_service,
            market_data_service=app.state.market_data_service,
            risk_repo=persistence_repos.get("risk_repo"),
            events_repo=persistence_repos.get("events_repo"),
        )
    else:
        logger.info("risk engine disabled")

    if settings.execution_engine_enabled and settings.paper_trading_enabled:
        app.state.execution_service = ExecutionService(
            settings=settings,
            risk_service=app.state.risk_service,
            market_data_service=app.state.market_data_service,
            approvals_repo=persistence_repos.get("approvals_repo"),
            trades_repo=persistence_repos.get("trades_repo"),
            positions_repo=persistence_repos.get("positions_repo"),
            events_repo=persistence_repos.get("events_repo"),
            persistence_session_factory=persistence_repos.get("session_factory"),
        )
        app.state.execution_service.recover_state()
    else:
        logger.info("execution engine disabled")

    app.state.replay_service = ReplayService(
        settings=settings,
        replay_repo=persistence_repos.get("replay_repo"),
    )
    if settings.optimization_engine_enabled:
        app.state.optimization_service = OptimizationService(
            settings=settings,
            optimization_repo=persistence_repos.get("optimization_repo"),
        )
    else:
        logger.info("optimization engine disabled")

    if settings.reporting_enabled and persistence_repos.get("trades_repo") is not None:
        aggregator = ReportAggregator(persistence_repos["trades_repo"])
        app.state.reporting_service = ReportingService(
            aggregator,
            settings=settings,
            reports_repo=persistence_repos.get("reports_repo"),
        )
    else:
        logger.info("reporting service disabled")

    if settings.shadow_mode_enabled:
        shadow_settings = settings.model_copy(update={"execution_mode": "shadow"})
        shadow_signal_service = SignalService(
            settings=shadow_settings,
            market_data_service=app.state.market_data_service,
        )
        shadow_risk_service = RiskService(
            settings=shadow_settings,
            signal_service=shadow_signal_service,
            market_data_service=app.state.market_data_service,
        )
        shadow_execution_service = ExecutionService(
            settings=shadow_settings,
            risk_service=shadow_risk_service,
            market_data_service=app.state.market_data_service,
            execution_mode="shadow",
            approvals_repo=persistence_repos.get("approvals_repo"),
            trades_repo=persistence_repos.get("trades_repo"),
            positions_repo=persistence_repos.get("positions_repo"),
            events_repo=persistence_repos.get("events_repo"),
            persistence_session_factory=persistence_repos.get("session_factory"),
        )
        shadow_execution_service.recover_state()
        runner = ShadowRunner(
            signal_service=shadow_signal_service,
            risk_service=shadow_risk_service,
            execution_service=shadow_execution_service,
            market_data_service=app.state.market_data_service,
            auto_approve=settings.shadow_auto_approve,
            events_repo=persistence_repos.get("events_repo"),
        )
        app.state.shadow_service = ShadowService(runner, settings=settings)
    else:
        logger.info("shadow service disabled")

    if all(
        persistence_repos.get(key) is not None
        for key in ("risk_repo", "approvals_repo", "positions_repo", "trades_repo", "portfolio_repo")
    ):
        app.state.portfolio_service = PortfolioService(
            settings=settings,
            risk_repo=persistence_repos.get("risk_repo"),
            approvals_repo=persistence_repos.get("approvals_repo"),
            positions_repo=persistence_repos.get("positions_repo"),
            trades_repo=persistence_repos.get("trades_repo"),
            portfolio_repo=persistence_repos.get("portfolio_repo"),
            events_repo=persistence_repos.get("events_repo"),
            rollout_service=app.state.rollout_service,
        )

    if settings.analytics_enabled and persistence_repos.get("trades_repo") is not None:
        app.state.analytics_service = AnalyticsService(
            settings=settings,
            trades_repo=persistence_repos.get("trades_repo"),
            analytics_repo=persistence_repos.get("analytics_repo"),
        )

    if all(
        persistence_repos.get(key) is not None
        for key in ("risk_repo", "approvals_repo", "trades_repo", "positions_repo", "locks_repo", "rollout_repo")
    ):
        app.state.rollout_service = LiveRolloutPolicy(
            settings=settings,
            rollout_repo=persistence_repos.get("rollout_repo"),
            positions_repo=persistence_repos.get("positions_repo"),
            trades_repo=persistence_repos.get("trades_repo"),
            events_repo=persistence_repos.get("events_repo"),
        )
        if app.state.portfolio_service is not None:
            app.state.portfolio_service.rollout_service = app.state.rollout_service
        live_adapter = BinanceLiveExecutionAdapter(settings=settings)
        lock_manager = LiveLockManager(
            locks_repo=persistence_repos.get("locks_repo"),
            events_repo=persistence_repos.get("events_repo"),
        )
        live_sync = LiveSyncService(live_adapter)
        live_reconciler = LiveReconciler(
            live_sync=live_sync,
            trades_repo=persistence_repos["trades_repo"],
            positions_repo=persistence_repos["positions_repo"],
            lock_manager=lock_manager,
            events_repo=persistence_repos.get("events_repo"),
        )
        app.state.live_controller = LiveController(
            settings=settings,
            adapter=live_adapter,
            lock_manager=lock_manager,
            risk_repo=persistence_repos["risk_repo"],
            approvals_repo=persistence_repos["approvals_repo"],
            trades_repo=persistence_repos["trades_repo"],
            positions_repo=persistence_repos["positions_repo"],
            events_repo=persistence_repos.get("events_repo"),
            market_data_service=app.state.market_data_service,
            execution_service=app.state.execution_service,
            reconciler=live_reconciler,
            rollout_service=app.state.rollout_service,
            portfolio_service=app.state.portfolio_service,
        )
        if app.state.execution_service is not None:
            app.state.execution_service.live_controller = app.state.live_controller
            app.state.execution_service.portfolio_service = app.state.portfolio_service

    app.state.startup_check_service = StartupCheckService(
        settings=settings,
        persistence_session_factory=persistence_repos.get("session_factory"),
        events_repo=persistence_repos.get("events_repo"),
        locks_repo=persistence_repos.get("locks_repo"),
        live_controller=app.state.live_controller,
        market_data_service=app.state.market_data_service,
        persistence_available=app.state.persistence_ready,
        persistence_error=app.state.persistence_error,
    )

    if settings.startup_preflight_enabled:
        app.state.startup_report = await app.state.startup_check_service.run_checks(write_probe_event=True)

    app.state.recovery_service = RecoveryService(
        settings=settings,
        execution_service=app.state.execution_service,
        live_controller=app.state.live_controller,
        approvals_repo=persistence_repos.get("approvals_repo"),
        positions_repo=persistence_repos.get("positions_repo"),
        events_repo=persistence_repos.get("events_repo"),
    )
    if settings.recovery_enabled:
        app.state.recovery_report = await app.state.recovery_service.run_startup_recovery()

    app.state.ops_service = OpsService(
        settings=settings,
        startup_checks=app.state.startup_check_service,
        recovery_service=app.state.recovery_service,
        execution_service=app.state.execution_service,
        live_controller=app.state.live_controller,
        market_data_service=app.state.market_data_service,
        approvals_repo=persistence_repos.get("approvals_repo"),
        events_repo=persistence_repos.get("events_repo"),
        locks_repo=persistence_repos.get("locks_repo"),
    )
    app.state.ops_service.set_startup_report(app.state.startup_report)


async def shutdown(app: FastAPI) -> None:
    execution_service = getattr(app.state, "execution_service", None)
    if execution_service is not None and hasattr(execution_service, "stop"):
        await execution_service.stop()

    replay_service = getattr(app.state, "replay_service", None)
    if replay_service is not None and hasattr(replay_service, "stop"):
        await replay_service.stop()

    optimization_service = getattr(app.state, "optimization_service", None)
    if optimization_service is not None and hasattr(optimization_service, "stop"):
        await optimization_service.stop()

    reporting_service = getattr(app.state, "reporting_service", None)
    if reporting_service is not None and hasattr(reporting_service, "stop"):
        await reporting_service.stop()

    shadow_service = getattr(app.state, "shadow_service", None)
    if shadow_service is not None and hasattr(shadow_service, "stop"):
        await shadow_service.stop()

    live_controller = getattr(app.state, "live_controller", None)
    if live_controller is not None and hasattr(live_controller, "adapter"):
        client = getattr(live_controller.adapter, "client", None)
        if client is not None:
            client.close()

    risk_service = getattr(app.state, "risk_service", None)
    if risk_service is not None and hasattr(risk_service, "stop"):
        await risk_service.stop()

    signal_service = getattr(app.state, "signal_service", None)
    if signal_service is not None and hasattr(signal_service, "stop"):
        await signal_service.stop()

    service = getattr(app.state, "market_data_service", None)
    if service is not None and hasattr(service, "stop"):
        await service.stop()

    logger.info("application shutdown service=%s", get_settings().app_name)

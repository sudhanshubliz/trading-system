from app.api.routes.approvals import router as approvals_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.control import router as control_router
from app.api.routes.health import router as health_router
from app.api.routes.live import router as live_router
from app.api.routes.market_data import router as market_data_router
from app.api.routes.ops import router as ops_router
from app.api.routes.optimization import router as optimization_router
from app.api.routes.pnl import router as pnl_router
from app.api.routes.positions import router as positions_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.replay import router as replay_router
from app.api.routes.reports import router as reports_router
from app.api.routes.rollout import router as rollout_router
from app.api.routes.risk import router as risk_router
from app.api.routes.shadow import router as shadow_router
from app.api.routes.signals import router as signals_router
from app.api.routes.trades import router as trades_router

__all__ = [
    "approvals_router",
    "analytics_router",
    "control_router",
    "health_router",
    "live_router",
    "market_data_router",
    "ops_router",
    "optimization_router",
    "pnl_router",
    "positions_router",
    "portfolio_router",
    "replay_router",
    "reports_router",
    "rollout_router",
    "risk_router",
    "shadow_router",
    "signals_router",
    "trades_router",
]

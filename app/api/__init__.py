from fastapi import APIRouter

from app.api.routes.approvals import router as approvals_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.control import router as control_router
from app.api.routes.health import router as health_router
from app.api.routes.market_data import router as market_data_router
from app.api.routes.live import router as live_router
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

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(ops_router, tags=["ops"])
api_router.include_router(analytics_router, tags=["analytics"])
api_router.include_router(market_data_router, tags=["market-data"])
api_router.include_router(live_router, tags=["live"])
api_router.include_router(signals_router, tags=["signals"])
api_router.include_router(risk_router, tags=["risk"])
api_router.include_router(approvals_router, tags=["approvals"])
api_router.include_router(positions_router, tags=["positions"])
api_router.include_router(trades_router, tags=["trades"])
api_router.include_router(pnl_router, tags=["pnl"])
api_router.include_router(control_router, tags=["control"])
api_router.include_router(portfolio_router, tags=["portfolio"])
api_router.include_router(rollout_router, tags=["rollout"])
api_router.include_router(replay_router, tags=["replay"])
api_router.include_router(optimization_router, tags=["optimization"])
api_router.include_router(reports_router, tags=["reports"])
api_router.include_router(shadow_router, tags=["shadow"])

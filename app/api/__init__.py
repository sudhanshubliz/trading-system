from fastapi import APIRouter

from app.api.routes.alpha import router as alpha_router
from app.api.routes.approvals import router as approvals_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.arbitrage import router as arbitrage_router
from app.api.routes.control import router as control_router
from app.api.routes.execution_quality import router as execution_quality_router
from app.api.routes.events import router as events_router
from app.api.routes.features import router as features_router
from app.api.routes.health import router as health_router
from app.api.routes.market_data import router as market_data_router
from app.api.routes.microstructure import router as microstructure_router
from app.api.routes.mirofish import router as mirofish_router
from app.api.routes.live import router as live_router
from app.api.routes.ops import router as ops_router
from app.api.routes.optimization import router as optimization_router
from app.api.routes.pnl import router as pnl_router
from app.api.routes.polymarket import router as polymarket_router
from app.api.routes.positions import router as positions_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.portfolio_brain import router as portfolio_brain_router
from app.api.routes.promotion import router as promotion_router
from app.api.routes.provider_health import router as provider_health_router
from app.api.routes.replay import router as replay_router
from app.api.routes.regime import router as regime_router
from app.api.routes.research import router as research_router
from app.api.routes.reports import router as reports_router
from app.api.routes.rollout import router as rollout_router
from app.api.routes.risk import router as risk_router
from app.api.routes.shadow import router as shadow_router
from app.api.routes.signals import router as signals_router
from app.api.routes.system_intelligence import router as system_router
from app.api.routes.system_records import router as system_records_router
from app.api.routes.system_stream import router as system_stream_router
from app.api.routes.strategy_owner import router as strategy_owner_router
from app.api.routes.trades import router as trades_router
from app.api.routes.wallets import router as wallets_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(ops_router, tags=["ops"])
api_router.include_router(system_router, tags=["system"])
api_router.include_router(system_records_router, tags=["system"])
api_router.include_router(system_stream_router, tags=["system"])
api_router.include_router(features_router, tags=["features"])
api_router.include_router(alpha_router, tags=["alpha"])
api_router.include_router(arbitrage_router, tags=["arbitrage"])
api_router.include_router(microstructure_router, tags=["microstructure"])
api_router.include_router(polymarket_router, tags=["polymarket"])
api_router.include_router(wallets_router, tags=["wallets"])
api_router.include_router(events_router, tags=["events"])
api_router.include_router(regime_router, tags=["regime"])
api_router.include_router(analytics_router, tags=["analytics"])
api_router.include_router(market_data_router, tags=["market-data"])
api_router.include_router(live_router, tags=["live"])
api_router.include_router(signals_router, tags=["signals"])
api_router.include_router(strategy_owner_router, tags=["strategy-owner"])
api_router.include_router(risk_router, tags=["risk"])
api_router.include_router(approvals_router, tags=["approvals"])
api_router.include_router(positions_router, tags=["positions"])
api_router.include_router(trades_router, tags=["trades"])
api_router.include_router(pnl_router, tags=["pnl"])
api_router.include_router(execution_quality_router, tags=["execution-quality"])
api_router.include_router(control_router, tags=["control"])
api_router.include_router(portfolio_router, tags=["portfolio"])
api_router.include_router(portfolio_brain_router, tags=["portfolio"])
api_router.include_router(promotion_router, tags=["promotion"])
api_router.include_router(provider_health_router, tags=["provider-health"])
api_router.include_router(rollout_router, tags=["rollout"])
api_router.include_router(replay_router, tags=["replay"])
api_router.include_router(research_router, tags=["research"])
api_router.include_router(optimization_router, tags=["optimization"])
api_router.include_router(reports_router, tags=["reports"])
api_router.include_router(shadow_router, tags=["shadow"])
api_router.include_router(mirofish_router, tags=["simulation"])

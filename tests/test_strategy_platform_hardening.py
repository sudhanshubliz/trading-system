from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config.settings import get_settings
from app.event_signals.service import EventSignalsService
from app.execution.engine import PaperExecutionEngine
from app.execution.types import Approval
from app.market_data.types import Candle, OrderBookLevel, OrderBookSnapshot, TickerSnapshot
from app.polymarket.types import PolymarketMarket, PolymarketOrderBook
from app.promotion.service import PromotionService
from app.probability.bayesian_model import update_probability
from app.probability.types import ProbabilityEvidence
from app.risk.types import RiskAssessment, RiskCheckResult
from app.strategies.latency_arbitrage.service import LatencyArbitrageService
from app.wallet_intel.service import WalletIntelService


def _settings(**updates: object):
    defaults = {
        "signals_supported_symbols": ["BTCUSDT", "ETHUSDT"],
        "latency_arb_enabled": True,
        "latency_arb_symbols": ["BTCUSDT"],
        "latency_arb_min_net_edge_bps": 50.0,
        "latency_arb_min_depth_usd": 1000.0,
        "polymarket_min_depth_usd": 1000.0,
        "event_min_importance_score": 0.5,
        "event_min_relevance_score": 0.5,
    }
    defaults.update(updates)
    return get_settings().model_copy(update=defaults)


def _assessment(now: datetime) -> RiskAssessment:
    return RiskAssessment(
        assessment_id="ras_1",
        signal_id="sig_1",
        symbol="BTCUSDT",
        side="long",
        strategy_name="trend_follow_continuation",
        final_decision="approved_for_review",
        account_balance=10000.0,
        max_risk_pct=2.0,
        risk_amount=100.0,
        stop_distance_abs=300.0,
        stop_distance_pct=0.5,
        position_size=0.5,
        notional_value=34000.0,
        estimated_fee=4.0,
        estimated_slippage_pct=0.05,
        open_risk_pct_before=0.0,
        open_risk_pct_after=1.0,
        daily_drawdown_pct=0.0,
        weekly_drawdown_pct=0.0,
        min_reward_risk_ratio=1.5,
        actual_reward_risk_ratio=1.8,
        confidence_threshold=65,
        risk_score=82,
        trade_classification="paper_candidate",
        passed_checks_count=5,
        failed_checks_count=0,
        checks=[RiskCheckResult(name="confidence", passed=True)],
        rejection_reasons=[],
        generated_trade_plan={
            "entry_price": 68500.0,
            "stop_loss": 68100.0,
            "target_1": 69000.0,
            "target_2": 69400.0,
            "position_size": 0.8,
        },
        active_risk_locks=[],
        assessed_at=now - timedelta(milliseconds=400),
    )


def test_paper_execution_engine_simulates_partial_fill_and_latency() -> None:
    now = datetime.now(timezone.utc)
    settings = _settings(
        paper_execution_min_fill_ratio=0.2,
        execution_sim_latency_ms=120,
        paper_execution_fill_latency_ms=180,
    )
    engine = PaperExecutionEngine(settings, time_provider=lambda: now)
    approval = Approval(
        approval_id="apr_1",
        assessment_id="ras_1",
        signal_id="sig_1",
        symbol="BTCUSDT",
        side="long",
        strategy_name="trend_follow_continuation",
        status="approved",
        created_at=now - timedelta(seconds=2),
        approved_at=now - timedelta(seconds=1),
    )
    snapshot = TickerSnapshot(
        symbol="BTCUSDT",
        last_price=68520.0,
        bid_price=68518.0,
        ask_price=68522.0,
        spread_bps=0.58,
        ticker_updated_at=now,
        orderbook_updated_at=now,
        snapshot_time=now,
    )
    order_book = OrderBookSnapshot(
        symbol="BTCUSDT",
        bids=[OrderBookLevel(price=68518.0, quantity=0.2)],
        asks=[OrderBookLevel(price=68522.0, quantity=0.15), OrderBookLevel(price=68523.0, quantity=0.2)],
        updated_at=now,
    )

    result = engine.execute(
        approval,
        _assessment(now),
        latest_market_price=68520.0,
        snapshot=snapshot,
        order_book=order_book,
        paused=False,
        provider_health_status="healthy",
    )

    assert result.trade.quantity < 0.8
    assert result.execution_details["partial_fill_ratio"] < 1.0
    assert result.execution_details["total_latency_ms"] >= 300.0
    assert result.execution_details["liquidity_used_pct"] > 0


def test_probability_update_moves_posterior_in_expected_direction() -> None:
    update = update_probability(
        0.5,
        [
            ProbabilityEvidence(source_name="event", direction_bias=1.0, confidence=0.8, weight=1.0),
            ProbabilityEvidence(source_name="wallet", direction_bias=1.0, confidence=0.6, weight=0.8),
        ],
    )
    assert update.posterior > 0.5
    assert update.effective_confidence > 0
    assert len(update.contributions) == 2


class StubPolymarketService:
    def __init__(self, *, stale: bool = False) -> None:
        updated_at = datetime.now(timezone.utc) - timedelta(seconds=20 if stale else 1)
        self.market = PolymarketMarket(
            market_id="pm_btc_hour",
            title="Will BTC be above $68,000 by 11pm?",
            category="crypto",
            event_slug="btc-hour",
            status="open",
            close_time=datetime.now(timezone.utc) + timedelta(hours=1),
            last_updated_at=updated_at,
            yes_price=0.41,
            no_price=0.62,
            metadata={},
        )
        self.order_book = PolymarketOrderBook(
            market_id="pm_btc_hour",
            yes_bid=0.4,
            yes_ask=0.41,
            no_bid=0.58,
            no_ask=0.59,
            depth_usd=8000.0,
            spread_bps=60.0,
            captured_at=updated_at,
        )

    async def list_markets(self):
        return [self.market]

    async def get_orderbook(self, market_id: str):
        return self.order_book


class StubMarketDataService:
    async def get_candles(self, symbol: str, timeframe: str):
        base = datetime.now(timezone.utc) - timedelta(minutes=15)
        return [
            Candle(open_time=base, open=67800.0, high=67880.0, low=67790.0, close=67840.0, volume=120.0, is_closed=True),
            Candle(open_time=base + timedelta(minutes=5), open=67840.0, high=67920.0, low=67820.0, close=67910.0, volume=140.0, is_closed=True),
            Candle(open_time=base + timedelta(minutes=10), open=67910.0, high=68040.0, low=67900.0, close=68010.0, volume=160.0, is_closed=True),
        ]


class StubProviderHealth:
    def any_unhealthy(self, names=None):
        return False


def test_latency_arb_rejects_stale_market_data() -> None:
    service = LatencyArbitrageService(
        settings=_settings(latency_arb_max_data_age_sec=5),
        market_data_service=StubMarketDataService(),
        polymarket_service=StubPolymarketService(stale=True),
        provider_health_service=StubProviderHealth(),
    )
    items = __import__("asyncio").run(service.evaluate())
    assert items == []


def test_event_signal_requires_new_evidence_before_re_emitting() -> None:
    settings = _settings()
    service = EventSignalsService(settings=settings)
    now = datetime.now(timezone.utc)
    event = service._normalize_event(
        {
            "event_id": "evt_1",
            "source": "mock",
            "title": "BTC ETF rumor",
            "summary": "Rumor",
            "category": "crypto",
            "event_type": "headline",
            "event_time": now,
            "detection_time": now,
            "entities": ["BTCUSDT"],
            "importance_score": 0.8,
            "sentiment_score": 0.4,
            "relevance_score": 0.7,
        }
    )
    first = service._build_signals(event)
    second = service._build_signals(event)
    assert len(first) == 1
    assert second == []


class StubExecutionQualityService:
    def list_records(self, strategy_name=None, limit=500):
        return []


class StubProviderHealthService:
    def build_summary(self):
        return {"count": 1, "healthy": 1}


def test_promotion_blockers_explain_undersampled_strategy() -> None:
    service = PromotionService(
        settings=_settings(promotion_min_sample_count=10),
        execution_quality_service=StubExecutionQualityService(),
        trades_repo=None,
        provider_health_service=StubProviderHealthService(),
        events_repo=None,
        repo=None,
    )
    blockers = service.get_blockers("latency_arbitrage")
    assert blockers["eligible"] is False
    assert "insufficient_sample_size" in blockers["blockers"]


class StubWalletProvider:
    async def list_wallets(self):
        return ["wal_1"]

    async def get_wallet_profile(self, wallet_id: str):
        now = datetime.now(timezone.utc)
        return {"first_seen": now - timedelta(days=10), "last_seen": now, "hit_rate": 0.7, "pnl_score": 0.65}

    async def get_wallet_positions(self, wallet_id: str):
        return []

    async def get_wallet_trade_history(self, wallet_id: str):
        now = datetime.now(timezone.utc)
        return [
            {"market": "pm_btc", "action": "buy_yes", "timestamp": now, "conviction": 0.8, "size": "large", "latency_seconds": 0.5, "associated_event": "evt_one"},
            {"market": "pm_btc", "action": "buy_yes", "timestamp": now, "conviction": 0.8, "size": "large", "latency_seconds": 0.4, "associated_event": "evt_one"},
            {"market": "pm_btc", "action": "buy_yes", "timestamp": now, "conviction": 0.8, "size": "large", "latency_seconds": 0.3, "associated_event": "evt_one"},
        ]

    async def get_wallet_activity_window(self, wallet_id: str):
        return []

    async def health_check(self):
        return {"status": "healthy"}


def test_wallet_signal_is_not_tradeable_when_suspicious() -> None:
    service = WalletIntelService(settings=_settings(), provider=StubWalletProvider())
    __import__("asyncio").run(service.refresh())
    signal = service.list_signals(limit=1)[0]
    assert signal.recommended_action == "ignore"
    assert signal.metadata["independent_confirmation_required"] is True

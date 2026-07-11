from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.config.settings import Settings
from app.execution.costs import calculate_prediction_market_fee
from app.execution.engine import PaperExecutionEngine
from app.execution.types import Approval
from app.market_data.types import Candle, PricePoint, TickerSnapshot
from app.polymarket.execution_market_data import PolymarketExecutionMarketDataAdapter
from app.polymarket.types import PolymarketBookLevel, PolymarketMarket, PolymarketOrderBook
from app.risk.engine import RiskEngine
from app.risk.types import AccountState, ExposureState
from app.simulation.mirofish_adapter import MiroFishAdapter
from app.strategies.latency_arbitrage.edge_calculator import walk_asks_for_notional
from app.strategies.latency_arbitrage.service import LatencyArbitrageService
from app.strategy_owner.registry import StrategyOwnerRegistry
from app.strategy_owner.service import StrategyOwnerService


def _settings(**updates: object) -> Settings:
    defaults: dict[str, object] = {
        "execution_mode": "paper",
        "latency_arb_enabled": True,
        "latency_arb_paper_only": True,
        "latency_arb_symbols": ["BTCUSDT"],
        "latency_arb_allowed_durations_minutes": [5, 15],
        "latency_arb_min_net_edge_bps": 100.0,
        "latency_arb_min_depth_usd": 1000.0,
        "latency_arb_max_spread_bps": 500.0,
        "latency_arb_max_data_age_sec": 10,
        "latency_arb_min_time_to_expiry_sec": 30,
        "latency_arb_paper_order_notional_usd": 50.0,
        "latency_arb_require_realtime_reference": True,
        "latency_arb_require_streaming_book": True,
        "min_confidence_score": 50,
        "min_net_edge_after_costs_bps": 10.0,
        "paper_execution_min_fill_ratio": 0.95,
        "stale_market_data_blocks_trading": True,
    }
    defaults.update(updates)
    return Settings(_env_file=None).model_copy(update=defaults)


class _RealLikePolymarketService:
    def __init__(self, now: datetime) -> None:
        self.market = PolymarketMarket(
            market_id="btc-up-5m",
            title="Will BTC be above $68,000 in 5 minutes?",
            category="crypto",
            event_slug="btc-up-5m",
            status="open",
            close_time=now + timedelta(minutes=4),
            last_updated_at=now,
            yes_price=0.44,
            no_price=0.56,
            condition_id="condition_btc_5m",
            yes_token_id="token_yes",
            no_token_id="token_no",
            liquidity_usd=20_000.0,
            fees_enabled=True,
            fee_rate=0.07,
            source="polymarket_gamma",
            metadata={"duration_minutes": 5, "start_time": now - timedelta(minutes=1)},
        )
        self.book = PolymarketOrderBook(
            market_id=self.market.market_id,
            yes_bid=0.43,
            yes_ask=0.45,
            no_bid=0.54,
            no_ask=0.56,
            depth_usd=20_000.0,
            spread_bps=450.0,
            captured_at=now,
            yes_bids=[PolymarketBookLevel(0.43, 2_000.0)],
            yes_asks=[PolymarketBookLevel(0.45, 2_000.0), PolymarketBookLevel(0.46, 2_000.0)],
            no_bids=[PolymarketBookLevel(0.54, 2_000.0)],
            no_asks=[PolymarketBookLevel(0.56, 2_000.0)],
            source="clob_websocket",
        )
        self.targets: dict[str, tuple[str, str]] = {}

    async def list_markets(self) -> list[PolymarketMarket]:
        return [self.market]

    async def get_orderbook(self, market_id: str) -> PolymarketOrderBook | None:
        return self.book if market_id == self.market.market_id else None

    async def get_provider_health(self) -> dict[str, object]:
        return {
            "status": "healthy",
            "metadata": {"source_is_mock": False, "stream_status": "connected"},
        }

    def register_execution_target(self, market_id: str, outcome: str) -> str:
        symbol = f"PM_TEST_{outcome.upper()}"
        self.targets[symbol] = (market_id, outcome.upper())
        return symbol

    def resolve_execution_symbol(self, symbol: str):
        target = self.targets.get(symbol)
        if target is None:
            return None
        from app.polymarket.execution_market_data import PolymarketExecutionTarget

        return PolymarketExecutionTarget(symbol, target[0], target[1])


class _RealtimeBinanceData:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.points = [
            PricePoint("BTCUSDT", 68_000.0, now - timedelta(seconds=300)),
            PricePoint("BTCUSDT", 68_300.0, now - timedelta(seconds=60)),
            PricePoint("BTCUSDT", 68_600.0, now - timedelta(seconds=30)),
            PricePoint("BTCUSDT", 69_000.0, now),
        ]

    async def get_snapshot(self, symbol: str) -> TickerSnapshot:
        return TickerSnapshot(
            symbol=symbol,
            last_price=69_000.0,
            bid_price=68_999.0,
            ask_price=69_001.0,
            ticker_updated_at=self.now,
            snapshot_time=self.now,
        )

    async def get_price_history(self, symbol: str, *, seconds: int) -> list[PricePoint]:
        return list(self.points)

    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        return [
            Candle(self.now - timedelta(minutes=10), 67_900, 68_100, 67_800, 68_000, 100, True),
            Candle(self.now - timedelta(minutes=5), 68_000, 69_100, 67_950, 69_000, 120, True),
        ]


class _HealthyProviders:
    def any_unhealthy(self, names: list[str] | None = None) -> bool:
        return False


def test_polymarket_fee_curve_and_depth_walk_are_cost_aware() -> None:
    fee = calculate_prediction_market_fee(shares=100.0, price=0.5, fee_rate=0.07)
    edge_fill = walk_asks_for_notional(
        [PolymarketBookLevel(0.4, 50.0), PolymarketBookLevel(0.5, 20.0)],
        40.0,
    )

    assert fee == pytest.approx(1.75)
    assert edge_fill["fill_ratio"] < 1.0
    assert edge_fill["fill_price"] > 0.4
    assert edge_fill["slippage_bps"] > 0


def test_real_time_latency_candidate_routes_through_risk_and_paper_execution() -> None:
    now = datetime.now(timezone.utc)
    settings = _settings()
    polymarket = _RealLikePolymarketService(now)
    service = LatencyArbitrageService(
        settings=settings,
        market_data_service=_RealtimeBinanceData(now),
        polymarket_service=polymarket,
        provider_health_service=_HealthyProviders(),
    )

    opportunities = asyncio.run(service.evaluate())

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.tradable is True
    assert opportunity.paper_only is True
    assert opportunity.book_source == "clob_websocket"
    assert opportunity.reference_fidelity == "realtime_price_history"

    candidate = StrategyOwnerRegistry(settings=settings).from_latency_arb(opportunity)
    risk_input = StrategyOwnerService(settings=settings)._to_risk_input(candidate)
    assessment = RiskEngine(settings).assess(
        risk_input,
        AccountState(5_000.0, 5_000.0, 5_000.0, 0.0, 0.0),
        ExposureState(0, 0.0),
        market_data_status="ok",
    )

    assert assessment.final_decision == "approved_for_review"
    assert assessment.notional_value is not None
    assert assessment.notional_value <= 50.0
    assert assessment.generated_trade_plan["fee_model"] == "polymarket_probability"
    assert assessment.generated_trade_plan["paper_only"] is True

    adapter = PolymarketExecutionMarketDataAdapter(polymarket)  # type: ignore[arg-type]
    execution_symbol = str(opportunity.metadata["execution_symbol"])
    snapshot = asyncio.run(adapter.get_snapshot(execution_symbol))
    book = asyncio.run(adapter.get_order_book(execution_symbol))
    approval = Approval(
        approval_id="approval_pm_1",
        assessment_id=assessment.assessment_id,
        signal_id=assessment.signal_id,
        symbol=execution_symbol,
        side="long",
        strategy_name="latency_arbitrage",
        status="approved",
        created_at=now,
        approved_at=now,
    )
    result = PaperExecutionEngine(settings, time_provider=lambda: now).execute(
        approval,
        assessment,
        latest_market_price=snapshot.last_price if snapshot is not None else None,
        snapshot=snapshot,
        order_book=book,
        paused=False,
        provider_health_status="healthy",
    )

    assert result.trade.execution_mode == "paper"
    assert result.trade.fee_model == "polymarket_probability"
    assert result.trade.fees_paid > 0
    assert result.execution_details["fee_model"] == "polymarket_probability"


def test_prediction_candidate_is_hard_rejected_in_live_mode() -> None:
    now = datetime.now(timezone.utc)
    settings = _settings(execution_mode="live")
    polymarket = _RealLikePolymarketService(now)
    opportunity = asyncio.run(
        LatencyArbitrageService(
            settings=settings,
            market_data_service=_RealtimeBinanceData(now),
            polymarket_service=polymarket,
            provider_health_service=_HealthyProviders(),
        ).evaluate()
    )[0]
    candidate = StrategyOwnerRegistry(settings=settings).from_latency_arb(opportunity)
    risk_input = StrategyOwnerService(settings=settings)._to_risk_input(candidate)

    assessment = RiskEngine(settings).assess(
        risk_input,
        AccountState(5_000.0, 5_000.0, 5_000.0, 0.0, 0.0),
        ExposureState(0, 0.0),
        market_data_status="ok",
    )

    assert assessment.final_decision == "rejected"
    assert "prediction_market_strategy_is_paper_only" in assessment.rejection_reasons


def test_external_mirofish_scenario_is_fresh_capped_and_advisory_only() -> None:
    now = datetime.now(timezone.utc)
    settings = _settings(
        enable_mirofish=True,
        mirofish_provider="external",
        mirofish_max_scenario_confidence=0.4,
        mirofish_max_data_age_seconds=30,
    )
    adapter = MiroFishAdapter(settings=settings)

    scenario = adapter.ingest_external(
        {
            "scenario_id": "scenario_1",
            "symbol_or_market": "btc-up-5m",
            "simulation_timestamp": now,
            "direction_bias": "long",
            "expected_crowd_bias": 0.8,
            "expected_volatility_shift": 0.3,
            "scenario_confidence": 0.95,
            "explanation": "External long-running scenario summary.",
            "source_run_id": "mirofish_run_1",
        }
    )
    candidate = StrategyOwnerRegistry(settings=settings).from_source_reading(
        adapter.as_source_reading(scenario)
    )

    assert scenario.scenario_confidence == 0.4
    assert scenario.advisory_only is True
    assert scenario.metadata["confidence_capped"] is True
    assert candidate.tradable is False
    assert candidate.requires_risk_review is False

    legacy_basket = replace(
        candidate,
        timestamp=now - timedelta(hours=1),
        tradable=True,
        requires_risk_review=True,
        metadata={"basket_required": True, "atomic_basket_execution_supported": False},
    )
    read_safe = StrategyOwnerService(settings=settings)._sanitize_candidate_for_read(legacy_basket)
    assert read_safe.tradable is False
    assert read_safe.requires_risk_review is False
    assert "atomic_basket_execution_unsupported" in read_safe.metadata["read_veto_factors"]

    with pytest.raises(ValueError, match="mirofish_scenario_stale"):
        adapter.ingest_external(
            {
                "scenario_id": "scenario_stale",
                "symbol_or_market": "btc-up-5m",
                "simulation_timestamp": now - timedelta(minutes=2),
                "direction_bias": "neutral",
                "expected_crowd_bias": 0.0,
                "expected_volatility_shift": 0.0,
                "scenario_confidence": 0.2,
            }
        )

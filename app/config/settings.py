from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str | list[str] | tuple[str, ...], *, upper: bool = False) -> list[str]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in value if str(item).strip()]

    if upper:
        return [item.upper() for item in items]

    return [item.lower() for item in items]


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="trading-system", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    database_url: str = Field(default="sqlite:///./trading_system.db", alias="DATABASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    trading_mode: str = Field(default="paper", alias="TRADING_MODE")
    market_data_enabled: bool = Field(default=True, alias="MARKET_DATA_ENABLED")
    binance_rest_base_url: str = Field(default="https://api.binance.com", alias="BINANCE_REST_BASE_URL")
    binance_ws_base_url: str = Field(
        default="wss://stream.binance.com:9443/stream",
        alias="BINANCE_WS_BASE_URL",
    )
    market_data_symbols: list[str] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT"],
        alias="MARKET_DATA_SYMBOLS",
    )
    market_data_timeframes: list[str] = Field(
        default_factory=lambda: ["5m", "15m", "1h"],
        alias="MARKET_DATA_TIMEFRAMES",
    )
    market_data_ticker_freshness_ms: int = Field(default=5000, alias="MARKET_DATA_TICKER_FRESHNESS_MS")
    market_data_orderbook_freshness_ms: int = Field(
        default=3000,
        alias="MARKET_DATA_ORDERBOOK_FRESHNESS_MS",
    )
    market_data_candle_freshness_ms: int = Field(default=90000, alias="MARKET_DATA_CANDLE_FRESHNESS_MS")
    market_data_ws_stale_ms: int = Field(default=10000, alias="MARKET_DATA_WS_STALE_MS")
    market_data_rest_fallback_interval_sec: int = Field(
        default=5,
        alias="MARKET_DATA_REST_FALLBACK_INTERVAL_SEC",
    )
    market_data_candle_limit: int = Field(default=300, alias="MARKET_DATA_CANDLE_LIMIT")
    market_data_orderbook_limit: int = Field(default=5, alias="MARKET_DATA_ORDERBOOK_LIMIT")
    signals_enabled: bool = Field(default=True, alias="SIGNALS_ENABLED")
    signals_supported_symbols: list[str] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT"],
        alias="SIGNALS_SUPPORTED_SYMBOLS",
    )
    signals_regime_timeframe: str = Field(default="1h", alias="SIGNALS_REGIME_TIMEFRAME")
    signals_setup_timeframe: str = Field(default="15m", alias="SIGNALS_SETUP_TIMEFRAME")
    signals_trigger_timeframe: str = Field(default="5m", alias="SIGNALS_TRIGGER_TIMEFRAME")
    signals_min_candle_count: int = Field(default=60, alias="SIGNALS_MIN_CANDLE_COUNT")
    signals_store_limit: int = Field(default=200, alias="SIGNALS_STORE_LIMIT")
    ema_fast_period: int = Field(default=20, alias="EMA_FAST_PERIOD")
    ema_slow_period: int = Field(default=50, alias="EMA_SLOW_PERIOD")
    rsi_period: int = Field(default=14, alias="RSI_PERIOD")
    macd_fast_period: int = Field(default=12, alias="MACD_FAST_PERIOD")
    macd_slow_period: int = Field(default=26, alias="MACD_SLOW_PERIOD")
    macd_signal_period: int = Field(default=9, alias="MACD_SIGNAL_PERIOD")
    breakout_lookback: int = Field(default=20, alias="BREAKOUT_LOOKBACK")
    volume_lookback: int = Field(default=20, alias="VOLUME_LOOKBACK")
    risk_engine_enabled: bool = Field(default=True, alias="RISK_ENGINE_ENABLED")
    paper_account_start_balance: float = Field(default=10000.0, alias="PAPER_ACCOUNT_START_BALANCE")
    max_risk_per_trade_pct: float = Field(default=2.0, alias="MAX_RISK_PER_TRADE_PCT")
    min_confidence_score: int = Field(default=65, alias="MIN_CONFIDENCE_SCORE")
    min_reward_risk_ratio: float = Field(default=1.5, alias="MIN_REWARD_RISK_RATIO")
    max_concurrent_positions: int = Field(default=3, alias="MAX_CONCURRENT_POSITIONS")
    max_open_risk_pct: float = Field(default=6.0, alias="MAX_OPEN_RISK_PCT")
    max_daily_drawdown_pct: float = Field(default=4.0, alias="MAX_DAILY_DRAWDOWN_PCT")
    max_weekly_drawdown_pct: float = Field(default=10.0, alias="MAX_WEEKLY_DRAWDOWN_PCT")
    max_slippage_pct: float = Field(default=0.25, alias="MAX_SLIPPAGE_PCT")
    min_stop_distance_pct: float = Field(default=0.15, alias="MIN_STOP_DISTANCE_PCT")
    max_stop_distance_pct: float = Field(default=5.0, alias="MAX_STOP_DISTANCE_PCT")
    position_size_precision: int = Field(default=6, alias="POSITION_SIZE_PRECISION")
    risk_store_limit: int = Field(default=500, alias="RISK_STORE_LIMIT")
    min_notional_value: float = Field(default=10.0, alias="MIN_NOTIONAL_VALUE")
    execution_mode: str = Field(default="paper", alias="EXECUTION_MODE")
    execution_engine_enabled: bool = Field(default=True, alias="EXECUTION_ENGINE_ENABLED")
    paper_trading_enabled: bool = Field(default=True, alias="PAPER_TRADING_ENABLED")
    telegram_simulation_mode: bool = Field(default=True, alias="TELEGRAM_SIMULATION_MODE")
    persistence_enabled: bool = Field(default=True, alias="PERSISTENCE_ENABLED")
    persistence_db_url: str = Field(
        default="sqlite:///./trading_system_persistence.db",
        alias="PERSISTENCE_DB_URL",
    )
    shadow_mode_enabled: bool = Field(default=True, alias="SHADOW_MODE_ENABLED")
    shadow_auto_approve: bool = Field(default=True, alias="SHADOW_AUTO_APPROVE")
    shadow_store_limit: int = Field(default=500, alias="SHADOW_STORE_LIMIT")
    enable_live_trading: bool = Field(default=False, alias="ENABLE_LIVE_TRADING")
    live_trading_armed: bool = Field(default=False, alias="LIVE_TRADING_ARMED")
    live_execution_mode: str = Field(default="paper", alias="LIVE_EXECUTION_MODE")
    binance_api_key: str = Field(default="", alias="BINANCE_API_KEY")
    binance_api_secret: str = Field(default="", alias="BINANCE_API_SECRET")
    binance_base_url: str = Field(default="https://api.binance.com", alias="BINANCE_BASE_URL")
    binance_order_timeout_sec: int = Field(default=10, alias="BINANCE_ORDER_TIMEOUT_SEC")
    live_require_explicit_approval: bool = Field(default=True, alias="LIVE_REQUIRE_EXPLICIT_APPROVAL")
    live_max_position_notional: float = Field(default=1000.0, alias="LIVE_MAX_POSITION_NOTIONAL")
    live_max_order_notional: float = Field(default=500.0, alias="LIVE_MAX_ORDER_NOTIONAL")
    live_max_daily_loss_pct: float = Field(default=3.0, alias="LIVE_MAX_DAILY_LOSS_PCT")
    live_max_weekly_loss_pct: float = Field(default=8.0, alias="LIVE_MAX_WEEKLY_LOSS_PCT")
    live_max_consecutive_losses: int = Field(default=3, alias="LIVE_MAX_CONSECUTIVE_LOSSES")
    live_max_open_positions: int = Field(default=2, alias="LIVE_MAX_OPEN_POSITIONS")
    live_max_open_risk_pct: float = Field(default=4.0, alias="LIVE_MAX_OPEN_RISK_PCT")
    live_reconciliation_enabled: bool = Field(default=True, alias="LIVE_RECONCILIATION_ENABLED")
    live_reconciliation_interval_sec: int = Field(default=15, alias="LIVE_RECONCILIATION_INTERVAL_SEC")
    live_allow_market_orders: bool = Field(default=False, alias="LIVE_ALLOW_MARKET_ORDERS")
    live_allow_limit_orders: bool = Field(default=True, alias="LIVE_ALLOW_LIMIT_ORDERS")
    live_slippage_guard_pct: float = Field(default=0.30, alias="LIVE_SLIPPAGE_GUARD_PCT")
    live_stale_data_block_sec: int = Field(default=10, alias="LIVE_STALE_DATA_BLOCK_SEC")
    live_locks_enabled: bool = Field(default=True, alias="LIVE_LOCKS_ENABLED")
    live_lock_store_limit: int = Field(default=500, alias="LIVE_LOCK_STORE_LIMIT")
    rollout_policy_enabled: bool = Field(default=True, alias="ROLLOUT_POLICY_ENABLED")
    live_max_capital_total: float = Field(default=1000.0, alias="LIVE_MAX_CAPITAL_TOTAL")
    live_initial_capital_limit: float = Field(default=100.0, alias="LIVE_INITIAL_CAPITAL_LIMIT")
    live_phase_default: str = Field(default="disabled", alias="LIVE_PHASE_DEFAULT")
    live_allowed_phases: list[str] = Field(
        default_factory=lambda: ["disabled", "micro", "limited", "scaled"],
        alias="LIVE_ALLOWED_PHASES",
    )
    live_scaling_step_capital: float = Field(default=100.0, alias="LIVE_SCALING_STEP_CAPITAL")
    live_scaling_min_trades: int = Field(default=20, alias="LIVE_SCALING_MIN_TRADES")
    live_scaling_min_win_rate: float = Field(default=50.0, alias="LIVE_SCALING_MIN_WIN_RATE")
    live_scaling_min_profit_factor: float = Field(default=1.15, alias="LIVE_SCALING_MIN_PROFIT_FACTOR")
    live_scaling_max_drawdown_pct: float = Field(default=8.0, alias="LIVE_SCALING_MAX_DRAWDOWN_PCT")
    live_scaling_max_daily_loss_pct: float = Field(default=2.5, alias="LIVE_SCALING_MAX_DAILY_LOSS_PCT")
    live_scaling_max_weekly_loss_pct: float = Field(default=6.0, alias="LIVE_SCALING_MAX_WEEKLY_LOSS_PCT")
    live_strategy_max_capital_pct: float = Field(default=50.0, alias="LIVE_STRATEGY_MAX_CAPITAL_PCT")
    live_symbol_max_capital_pct: float = Field(default=40.0, alias="LIVE_SYMBOL_MAX_CAPITAL_PCT")
    live_portfolio_max_correlated_positions: int = Field(
        default=2,
        alias="LIVE_PORTFOLIO_MAX_CORRELATED_POSITIONS",
    )
    live_auto_deescalate_enabled: bool = Field(default=True, alias="LIVE_AUTO_DEESCALATE_ENABLED")
    live_auto_disarm_on_critical_rollback: bool = Field(
        default=True,
        alias="LIVE_AUTO_DISARM_ON_CRITICAL_ROLLBACK",
    )
    live_rollout_store_limit: int = Field(default=500, alias="LIVE_ROLLOUT_STORE_LIMIT")
    portfolio_enabled: bool = Field(default=True, alias="PORTFOLIO_ENABLED")
    portfolio_max_total_capital_pct: float = Field(default=100.0, alias="PORTFOLIO_MAX_TOTAL_CAPITAL_PCT")
    portfolio_max_per_strategy_pct: float = Field(default=40.0, alias="PORTFOLIO_MAX_PER_STRATEGY_PCT")
    portfolio_max_per_symbol_pct: float = Field(default=35.0, alias="PORTFOLIO_MAX_PER_SYMBOL_PCT")
    portfolio_max_open_positions: int = Field(default=5, alias="PORTFOLIO_MAX_OPEN_POSITIONS")
    portfolio_max_correlated_cluster_pct: float = Field(
        default=60.0,
        alias="PORTFOLIO_MAX_CORRELATED_CLUSTER_PCT",
    )
    portfolio_max_single_trade_pct: float = Field(default=20.0, alias="PORTFOLIO_MAX_SINGLE_TRADE_PCT")
    portfolio_reserve_cash_pct: float = Field(default=10.0, alias="PORTFOLIO_RESERVE_CASH_PCT")
    portfolio_rebalance_enabled: bool = Field(default=True, alias="PORTFOLIO_REBALANCE_ENABLED")
    portfolio_ranking_mode: str = Field(default="score", alias="PORTFOLIO_RANKING_MODE")
    portfolio_correlation_mode: str = Field(default="simple", alias="PORTFOLIO_CORRELATION_MODE")
    analytics_enabled: bool = Field(default=True, alias="ANALYTICS_ENABLED")
    analytics_store_limit: int = Field(default=500, alias="ANALYTICS_STORE_LIMIT")
    analytics_lookback_days: int = Field(default=30, alias="ANALYTICS_LOOKBACK_DAYS")
    regime_classification_enabled: bool = Field(default=True, alias="REGIME_CLASSIFICATION_ENABLED")
    regime_volatility_lookback: int = Field(default=20, alias="REGIME_VOLATILITY_LOOKBACK")
    regime_trend_lookback: int = Field(default=50, alias="REGIME_TREND_LOOKBACK")
    ops_enabled: bool = Field(default=True, alias="OPS_ENABLED")
    startup_preflight_enabled: bool = Field(default=True, alias="STARTUP_PREFLIGHT_ENABLED")
    require_persistence_for_boot: bool = Field(default=True, alias="REQUIRE_PERSISTENCE_FOR_BOOT")
    require_market_data_for_live: bool = Field(default=False, alias="REQUIRE_MARKET_DATA_FOR_LIVE")
    recovery_enabled: bool = Field(default=True, alias="RECOVERY_ENABLED")
    alerts_enabled: bool = Field(default=True, alias="ALERTS_ENABLED")
    healthcheck_deep_enabled: bool = Field(default=True, alias="HEALTHCHECK_DEEP_ENABLED")
    status_event_limit: int = Field(default=100, alias="STATUS_EVENT_LIMIT")
    deployment_mode: str = Field(default="local", alias="DEPLOYMENT_MODE")
    http_port: int = Field(default=8000, alias="HTTP_PORT")
    readiness_requires_db: bool = Field(default=True, alias="READINESS_REQUIRES_DB")
    readiness_requires_persistence: bool = Field(default=True, alias="READINESS_REQUIRES_PERSISTENCE")
    liveness_fail_on_deadlock: bool = Field(default=False, alias="LIVENESS_FAIL_ON_DEADLOCK")
    telegram_confirm_dangerous_actions: bool = Field(
        default=True,
        alias="TELEGRAM_CONFIRM_DANGEROUS_ACTIONS",
    )
    telegram_runtime_enabled: bool = Field(default=True, alias="TELEGRAM_RUNTIME_ENABLED")
    global_pause: bool = Field(default=False, alias="GLOBAL_PAUSE")
    stale_market_data_blocks_trading: bool = Field(
        default=True,
        alias="STALE_MARKET_DATA_BLOCKS_TRADING",
    )
    reporting_enabled: bool = Field(default=True, alias="REPORTING_ENABLED")
    report_store_limit: int = Field(default=200, alias="REPORT_STORE_LIMIT")
    shadow_default_slippage_pct: float = Field(default=0.0, alias="SHADOW_DEFAULT_SLIPPAGE_PCT")
    optimization_engine_enabled: bool = Field(default=True, alias="OPTIMIZATION_ENGINE_ENABLED")
    optimization_store_limit: int = Field(default=50, alias="OPTIMIZATION_STORE_LIMIT")
    optimization_max_combinations: int = Field(default=200, alias="OPTIMIZATION_MAX_COMBINATIONS")
    optimization_default_symbols: list[str] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT"],
        alias="OPTIMIZATION_DEFAULT_SYMBOLS",
    )
    optimization_default_initial_balance: float = Field(
        default=10000.0,
        alias="OPTIMIZATION_DEFAULT_INITIAL_BALANCE",
    )
    optimization_min_trades: int = Field(default=20, alias="OPTIMIZATION_MIN_TRADES")
    optimization_min_profit_factor: float = Field(default=1.2, alias="OPTIMIZATION_MIN_PROFIT_FACTOR")
    optimization_max_drawdown_pct: float = Field(default=25.0, alias="OPTIMIZATION_MAX_DRAWDOWN_PCT")
    optimization_walk_forward_splits: int = Field(default=3, alias="OPTIMIZATION_WALK_FORWARD_SPLITS")
    optimization_require_walk_forward: bool = Field(
        default=True,
        alias="OPTIMIZATION_REQUIRE_WALK_FORWARD",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("market_data_symbols", mode="before")
    @classmethod
    def validate_market_data_symbols(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=True)

    @field_validator("market_data_timeframes", mode="before")
    @classmethod
    def validate_market_data_timeframes(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=False)

    @field_validator("signals_supported_symbols", mode="before")
    @classmethod
    def validate_signals_supported_symbols(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=True)

    @field_validator("optimization_default_symbols", mode="before")
    @classmethod
    def validate_optimization_default_symbols(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=True)

    @field_validator("live_allowed_phases", mode="before")
    @classmethod
    def validate_live_allowed_phases(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=False)

    @field_validator(
        "signals_regime_timeframe",
        "signals_setup_timeframe",
        "signals_trigger_timeframe",
        "live_phase_default",
        "portfolio_ranking_mode",
        "portfolio_correlation_mode",
        mode="before",
    )
    @classmethod
    def validate_signal_timeframes(cls, value: str) -> str:
        return str(value).strip().lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

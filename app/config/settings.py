from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, DotEnvSettingsSource, EnvSettingsSource, SettingsConfigDict


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
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:3000", "http://localhost:3000"],
        alias="CORS_ALLOWED_ORIGINS",
    )
    dashboard_stream_enabled: bool = Field(default=True, alias="DASHBOARD_STREAM_ENABLED")
    dashboard_stream_interval_sec: int = Field(default=5, alias="DASHBOARD_STREAM_INTERVAL_SEC")
    database_url: str = Field(default="sqlite:///./trading_system.db", alias="DATABASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    trading_mode: str = Field(default="paper", alias="TRADING_MODE")
    market_data_enabled: bool = Field(default=True, alias="MARKET_DATA_ENABLED")
    binance_rest_base_url: str = Field(default="https://api.binance.com", alias="BINANCE_REST_BASE_URL")
    binance_futures_rest_base_url: str = Field(
        default="https://fapi.binance.com",
        alias="BINANCE_FUTURES_REST_BASE_URL",
    )
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
    market_data_trade_cache_limit: int = Field(default=200, alias="MARKET_DATA_TRADE_CACHE_LIMIT")
    market_data_funding_cache_limit: int = Field(default=128, alias="MARKET_DATA_FUNDING_CACHE_LIMIT")
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
    signals_pullback_tolerance_pct: float = Field(default=0.006, alias="SIGNALS_PULLBACK_TOLERANCE_PCT")
    signals_min_trigger_range_pct: float = Field(default=0.08, alias="SIGNALS_MIN_TRIGGER_RANGE_PCT")
    signals_breakout_buffer_pct: float = Field(default=0.001, alias="SIGNALS_BREAKOUT_BUFFER_PCT")
    signals_rsi_long_min: float = Field(default=50.0, alias="SIGNALS_RSI_LONG_MIN")
    signals_rsi_long_max: float = Field(default=72.0, alias="SIGNALS_RSI_LONG_MAX")
    signals_rsi_short_min: float = Field(default=28.0, alias="SIGNALS_RSI_SHORT_MIN")
    signals_rsi_short_max: float = Field(default=60.0, alias="SIGNALS_RSI_SHORT_MAX")
    ema_fast_period: int = Field(default=20, alias="EMA_FAST_PERIOD")
    ema_slow_period: int = Field(default=50, alias="EMA_SLOW_PERIOD")
    rsi_period: int = Field(default=14, alias="RSI_PERIOD")
    macd_fast_period: int = Field(default=12, alias="MACD_FAST_PERIOD")
    macd_slow_period: int = Field(default=26, alias="MACD_SLOW_PERIOD")
    macd_signal_period: int = Field(default=9, alias="MACD_SIGNAL_PERIOD")
    breakout_lookback: int = Field(default=20, alias="BREAKOUT_LOOKBACK")
    volume_lookback: int = Field(default=20, alias="VOLUME_LOOKBACK")
    alpha_fusion_enabled: bool = Field(default=True, alias="ALPHA_FUSION_ENABLED")
    alpha_feature_timeframes: list[str] = Field(
        default_factory=lambda: ["5m", "15m", "1h"],
        alias="ALPHA_FEATURE_TIMEFRAMES",
    )
    alpha_atr_period: int = Field(default=14, alias="ALPHA_ATR_PERIOD")
    alpha_target_atr_pct: float = Field(default=1.2, alias="ALPHA_TARGET_ATR_PCT")
    alpha_fusion_store_limit: int = Field(default=300, alias="ALPHA_FUSION_STORE_LIMIT")
    alpha_source_store_limit: int = Field(default=500, alias="ALPHA_SOURCE_STORE_LIMIT")
    alpha_weight_trend: float = Field(default=0.32, alias="ALPHA_WEIGHT_TREND")
    alpha_weight_momentum: float = Field(default=0.24, alias="ALPHA_WEIGHT_MOMENTUM")
    alpha_weight_breakout: float = Field(default=0.20, alias="ALPHA_WEIGHT_BREAKOUT")
    alpha_weight_volatility: float = Field(default=0.14, alias="ALPHA_WEIGHT_VOLATILITY")
    alpha_weight_regime: float = Field(default=0.10, alias="ALPHA_WEIGHT_REGIME")
    alpha_weight_arbitrage: float = Field(default=0.05, alias="ALPHA_WEIGHT_ARBITRAGE")
    alpha_weight_microstructure: float = Field(default=0.05, alias="ALPHA_WEIGHT_MICROSTRUCTURE")
    alpha_weight_wallet: float = Field(default=0.05, alias="ALPHA_WEIGHT_WALLET")
    alpha_long_threshold: float = Field(default=0.60, alias="ALPHA_LONG_THRESHOLD")
    alpha_short_threshold: float = Field(default=0.60, alias="ALPHA_SHORT_THRESHOLD")
    feature_store_limit: int = Field(default=500, alias="FEATURE_STORE_LIMIT")
    feature_bollinger_period: int = Field(default=20, alias="FEATURE_BOLLINGER_PERIOD")
    feature_bollinger_stddev: float = Field(default=2.0, alias="FEATURE_BOLLINGER_STDDEV")
    feature_keltner_period: int = Field(default=20, alias="FEATURE_KELTNER_PERIOD")
    feature_keltner_atr_mult: float = Field(default=1.5, alias="FEATURE_KELTNER_ATR_MULT")
    feature_market_structure_lookback: int = Field(default=12, alias="FEATURE_MARKET_STRUCTURE_LOOKBACK")
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
    shadow_cycle_interval_sec: int = Field(default=30, alias="SHADOW_CYCLE_INTERVAL_SEC")
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
    regime_store_limit: int = Field(default=500, alias="REGIME_STORE_LIMIT")
    regime_trend_strength_threshold: float = Field(default=0.35, alias="REGIME_TREND_STRENGTH_THRESHOLD")
    regime_volatility_high_pct: float = Field(default=2.0, alias="REGIME_VOLATILITY_HIGH_PCT")
    regime_compression_pct_threshold: float = Field(default=3.0, alias="REGIME_COMPRESSION_PCT_THRESHOLD")
    regime_risk_off_volatility_multiplier: float = Field(
        default=1.6,
        alias="REGIME_RISK_OFF_VOLATILITY_MULTIPLIER",
    )
    research_enabled: bool = Field(default=True, alias="RESEARCH_ENABLED")
    research_store_limit: int = Field(default=200, alias="RESEARCH_STORE_LIMIT")
    promotion_min_sample_count: int = Field(default=50, alias="PROMOTION_MIN_SAMPLE_COUNT")
    promotion_min_expectancy: float = Field(default=0.05, alias="PROMOTION_MIN_EXPECTANCY")
    promotion_max_drawdown_pct: float = Field(default=8.0, alias="PROMOTION_MAX_DRAWDOWN_PCT")
    promotion_min_execution_quality: float = Field(default=0.6, alias="PROMOTION_MIN_EXECUTION_QUALITY")
    provider_health_stale_sec: int = Field(default=60, alias="PROVIDER_HEALTH_STALE_SEC")
    provider_health_error_threshold: int = Field(default=3, alias="PROVIDER_HEALTH_ERROR_THRESHOLD")
    enable_provider_health: bool = Field(default=True, alias="ENABLE_PROVIDER_HEALTH")
    provider_health_degrade_threshold: float = Field(default=0.75, alias="PROVIDER_HEALTH_DEGRADE_THRESHOLD")
    provider_health_unhealthy_threshold: int = Field(default=3, alias="PROVIDER_HEALTH_UNHEALTHY_THRESHOLD")
    openclaw_bridge_enabled: bool = Field(default=False, alias="OPENCLAW_BRIDGE_ENABLED")
    enable_openclaw_bridge: bool = Field(default=False, alias="ENABLE_OPENCLAW_BRIDGE")
    openclaw_bridge_base_url: str = Field(default="", alias="OPENCLAW_BRIDGE_BASE_URL")
    openclaw_bridge_timeout_sec: int = Field(default=5, alias="OPENCLAW_BRIDGE_TIMEOUT_SEC")
    openclaw_dry_run: bool = Field(default=True, alias="OPENCLAW_DRY_RUN")
    openclaw_alert_min_severity: str = Field(default="medium", alias="OPENCLAW_ALERT_MIN_SEVERITY")
    mirofish_adapter_enabled: bool = Field(default=False, alias="MIROFISH_ADAPTER_ENABLED")
    enable_mirofish: bool = Field(default=False, alias="ENABLE_MIROFISH")
    mirofish_adapter_mode: str = Field(default="mock", alias="MIROFISH_ADAPTER_MODE")
    mirofish_provider: str = Field(default="mock", alias="MIROFISH_PROVIDER")
    mirofish_adapter_path: str = Field(default="", alias="MIROFISH_ADAPTER_PATH")
    mirofish_timeout_ms: int = Field(default=1000, alias="MIROFISH_TIMEOUT_MS")
    mirofish_max_data_age_seconds: int = Field(default=120, alias="MIROFISH_MAX_DATA_AGE_SECONDS")
    polymarket_provider_enabled: bool = Field(default=False, alias="POLYMARKET_PROVIDER_ENABLED")
    enable_polymarket_engine: bool = Field(default=True, alias="ENABLE_POLYMARKET_ENGINE")
    polymarket_provider: str = Field(default="mock", alias="POLYMARKET_PROVIDER")
    polymarket_provider_mode: str = Field(default="mock", alias="POLYMARKET_PROVIDER_MODE")
    polymarket_api_base_url: str = Field(default="", alias="POLYMARKET_API_BASE_URL")
    polymarket_base_url: str = Field(default="https://gamma-api.polymarket.com", alias="POLYMARKET_BASE_URL")
    polymarket_timeout_ms: int = Field(default=3000, alias="POLYMARKET_TIMEOUT_MS")
    polymarket_max_data_age_seconds: int = Field(default=180, alias="POLYMARKET_MAX_DATA_AGE_SECONDS")
    polymarket_min_net_edge_bps: float = Field(default=6.0, alias="POLYMARKET_MIN_NET_EDGE_BPS")
    polymarket_min_depth_usd: float = Field(default=5000.0, alias="POLYMARKET_MIN_DEPTH_USD")
    polymarket_linked_rules_enabled: bool = Field(default=True, alias="POLYMARKET_LINKED_RULES_ENABLED")
    wallet_provider_enabled: bool = Field(default=False, alias="WALLET_PROVIDER_ENABLED")
    enable_wallet_intel: bool = Field(default=True, alias="ENABLE_WALLET_INTEL")
    wallet_provider: str = Field(default="mock", alias="WALLET_PROVIDER")
    wallet_provider_mode: str = Field(default="mock", alias="WALLET_PROVIDER_MODE")
    wallet_provider_base_url: str = Field(default="", alias="WALLET_PROVIDER_BASE_URL")
    wallet_provider_timeout_ms: int = Field(default=3000, alias="WALLET_PROVIDER_TIMEOUT_MS")
    wallet_max_data_age_seconds: int = Field(default=600, alias="WALLET_MAX_DATA_AGE_SECONDS")
    wallet_min_quality_score: float = Field(default=0.55, alias="WALLET_MIN_QUALITY_SCORE")
    wallet_max_crowding_score: float = Field(default=0.75, alias="WALLET_MAX_CROWDING_SCORE")
    wallet_signal_mode: str = Field(default="hybrid", alias="WALLET_SIGNAL_MODE")
    wallet_score_follow_threshold: float = Field(default=0.7, alias="WALLET_SCORE_FOLLOW_THRESHOLD")
    wallet_score_fade_threshold: float = Field(default=0.3, alias="WALLET_SCORE_FADE_THRESHOLD")
    event_provider_enabled: bool = Field(default=False, alias="EVENT_PROVIDER_ENABLED")
    enable_event_signals: bool = Field(default=True, alias="ENABLE_EVENT_SIGNALS")
    event_provider: str = Field(default="mock", alias="EVENT_PROVIDER")
    event_provider_mode: str = Field(default="mock", alias="EVENT_PROVIDER_MODE")
    event_provider_timeout_ms: int = Field(default=3000, alias="EVENT_PROVIDER_TIMEOUT_MS")
    event_dedupe_window_minutes: int = Field(default=120, alias="EVENT_DEDUPE_WINDOW_MINUTES")
    event_max_data_age_seconds: int = Field(default=7200, alias="EVENT_MAX_DATA_AGE_SECONDS")
    event_news_feed_urls: list[str] = Field(default_factory=list, alias="EVENT_NEWS_FEED_URLS")
    event_sentiment_feed_url: str = Field(default="", alias="EVENT_SENTIMENT_FEED_URL")
    event_calendar_feed_url: str = Field(default="", alias="EVENT_CALENDAR_FEED_URL")
    event_custom_feed_url: str = Field(default="", alias="EVENT_CUSTOM_FEED_URL")
    event_decay_half_life_minutes: int = Field(default=90, alias="EVENT_DECAY_HALF_LIFE_MINUTES")
    event_min_importance_score: float = Field(default=0.55, alias="EVENT_MIN_IMPORTANCE_SCORE")
    event_min_relevance_score: float = Field(default=0.5, alias="EVENT_MIN_RELEVANCE_SCORE")
    basis_enabled: bool = Field(default=False, alias="BASIS_ENABLED")
    basis_min_edge_bps: float = Field(default=12.0, alias="BASIS_MIN_EDGE_BPS")
    basis_max_funding_abs_pct: float = Field(default=0.08, alias="BASIS_MAX_FUNDING_ABS_PCT")
    enable_basis_funding_engine: bool = Field(default=False, alias="ENABLE_BASIS_FUNDING_ENGINE")
    funding_extreme_pos_threshold: float = Field(default=0.0005, alias="FUNDING_EXTREME_POS_THRESHOLD")
    funding_extreme_neg_threshold: float = Field(default=-0.0005, alias="FUNDING_EXTREME_NEG_THRESHOLD")
    basis_zscore_action_threshold: float = Field(default=1.5, alias="BASIS_ZSCORE_ACTION_THRESHOLD")
    basis_min_net_edge_bps: float = Field(default=8.0, alias="BASIS_MIN_NET_EDGE_BPS")
    basis_max_data_age_seconds: int = Field(default=120, alias="BASIS_MAX_DATA_AGE_SECONDS")
    basis_history_limit: int = Field(default=48, alias="BASIS_HISTORY_LIMIT")
    microstructure_enabled: bool = Field(default=False, alias="MICROSTRUCTURE_ENABLED")
    microstructure_imbalance_threshold: float = Field(default=0.15, alias="MICROSTRUCTURE_IMBALANCE_THRESHOLD")
    microstructure_max_spread_bps: float = Field(default=3.0, alias="MICROSTRUCTURE_MAX_SPREAD_BPS")
    enable_microstructure_engine: bool = Field(default=False, alias="ENABLE_MICROSTRUCTURE_ENGINE")
    microstructure_top_n_levels: int = Field(default=5, alias="MICROSTRUCTURE_TOP_N_LEVELS")
    microstructure_min_depth_usd: float = Field(default=25000.0, alias="MICROSTRUCTURE_MIN_DEPTH_USD")
    microstructure_max_relative_spread_bps: float = Field(
        default=4.0,
        alias="MICROSTRUCTURE_MAX_RELATIVE_SPREAD_BPS",
    )
    microstructure_stale_book_seconds: int = Field(default=3, alias="MICROSTRUCTURE_STALE_BOOK_SECONDS")
    microstructure_vol_shock_threshold: float = Field(default=0.35, alias="MICROSTRUCTURE_VOL_SHOCK_THRESHOLD")
    microstructure_signal_cooldown_seconds: int = Field(default=15, alias="MICROSTRUCTURE_SIGNAL_COOLDOWN_SECONDS")
    fusion_weight_polymarket: float = Field(default=0.15, alias="FUSION_WEIGHT_POLYMARKET")
    fusion_weight_wallet: float = Field(default=0.1, alias="FUSION_WEIGHT_WALLET")
    fusion_weight_event: float = Field(default=0.12, alias="FUSION_WEIGHT_EVENT")
    fusion_weight_mirofish: float = Field(default=0.08, alias="FUSION_WEIGHT_MIROFISH")
    enable_provider_health_veto: bool = Field(default=True, alias="ENABLE_PROVIDER_HEALTH_VETO")
    execution_sim_latency_ms: int = Field(default=150, alias="EXECUTION_SIM_LATENCY_MS")
    execution_sim_partial_fill_pct: float = Field(default=0.5, alias="EXECUTION_SIM_PARTIAL_FILL_PCT")
    execution_quality_enabled: bool = Field(default=True, alias="EXECUTION_QUALITY_ENABLED")
    execution_quality_bad_score_threshold: float = Field(
        default=0.45,
        alias="EXECUTION_QUALITY_BAD_SCORE_THRESHOLD",
    )
    execution_max_expected_slippage_bps: float = Field(
        default=12.0,
        alias="EXECUTION_MAX_EXPECTED_SLIPPAGE_BPS",
    )
    enable_stale_data_lock: bool = Field(default=True, alias="ENABLE_STALE_DATA_LOCK")
    enable_volatility_shock_lock: bool = Field(default=True, alias="ENABLE_VOLATILITY_SHOCK_LOCK")
    enable_execution_anomaly_lock: bool = Field(default=True, alias="ENABLE_EXECUTION_ANOMALY_LOCK")
    enable_liquidity_thin_lock: bool = Field(default=True, alias="ENABLE_LIQUIDITY_THIN_LOCK")
    enable_basis_data_integrity_lock: bool = Field(default=True, alias="ENABLE_BASIS_DATA_INTEGRITY_LOCK")
    enable_portfolio_brain: bool = Field(default=True, alias="ENABLE_PORTFOLIO_BRAIN")
    portfolio_max_strategy_weight: float = Field(default=0.35, alias="PORTFOLIO_MAX_STRATEGY_WEIGHT")
    portfolio_max_market_weight: float = Field(default=0.4, alias="PORTFOLIO_MAX_MARKET_WEIGHT")
    portfolio_drawdown_throttle_threshold: float = Field(default=0.08, alias="PORTFOLIO_DRAWDOWN_THROTTLE_THRESHOLD")
    portfolio_correlation_lookback: int = Field(default=90, alias="PORTFOLIO_CORRELATION_LOOKBACK")
    portfolio_bucket_cap_crypto_directional: float = Field(
        default=0.45,
        alias="PORTFOLIO_BUCKET_CAP_CRYPTO_DIRECTIONAL",
    )
    portfolio_bucket_cap_event_markets: float = Field(default=0.3, alias="PORTFOLIO_BUCKET_CAP_EVENT_MARKETS")
    portfolio_bucket_cap_wallet_follow: float = Field(default=0.2, alias="PORTFOLIO_BUCKET_CAP_WALLET_FOLLOW")
    enable_promotion_ladder: bool = Field(default=True, alias="ENABLE_PROMOTION_LADDER")
    promotion_max_drawdown: float = Field(default=8.0, alias="PROMOTION_MAX_DRAWDOWN")
    promotion_min_provider_health: float = Field(default=0.6, alias="PROMOTION_MIN_PROVIDER_HEALTH")
    replay_default_fidelity: str = Field(default="medium", alias="REPLAY_DEFAULT_FIDELITY")
    replay_allow_partial_external_data: bool = Field(default=True, alias="REPLAY_ALLOW_PARTIAL_EXTERNAL_DATA")
    enable_backfill_jobs: bool = Field(default=True, alias="ENABLE_BACKFILL_JOBS")
    backfill_batch_size: int = Field(default=250, alias="BACKFILL_BATCH_SIZE")
    backfill_retry_limit: int = Field(default=2, alias="BACKFILL_RETRY_LIMIT")
    backfill_resume_enabled: bool = Field(default=True, alias="BACKFILL_RESUME_ENABLED")
    incident_alert_min_severity: str = Field(default="medium", alias="INCIDENT_ALERT_MIN_SEVERITY")
    incident_auto_create_provider_failure: bool = Field(
        default=True,
        alias="INCIDENT_AUTO_CREATE_PROVIDER_FAILURE",
    )
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
        enable_decoding=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        csv_fields = {
            "market_data_symbols",
            "market_data_timeframes",
            "signals_supported_symbols",
            "alpha_feature_timeframes",
            "optimization_default_symbols",
            "live_allowed_phases",
            "event_news_feed_urls",
            "cors_allowed_origins",
        }

        class CsvEnvSettingsSource(EnvSettingsSource):
            def prepare_field_value(self, field_name, field, value, value_is_complex):  # type: ignore[override]
                if field_name in csv_fields and isinstance(value, str):
                    return value
                return super().prepare_field_value(field_name, field, value, value_is_complex)

        class CsvDotEnvSettingsSource(DotEnvSettingsSource):
            def prepare_field_value(self, field_name, field, value, value_is_complex):  # type: ignore[override]
                if field_name in csv_fields and isinstance(value, str):
                    return value
                return super().prepare_field_value(field_name, field, value, value_is_complex)

        return (
            init_settings,
            CsvEnvSettingsSource(settings_cls),
            CsvDotEnvSettingsSource(settings_cls),
            file_secret_settings,
        )

    @field_validator("market_data_symbols", mode="before")
    @classmethod
    def validate_market_data_symbols(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=True)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def validate_cors_allowed_origins(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("market_data_timeframes", mode="before")
    @classmethod
    def validate_market_data_timeframes(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=False)

    @field_validator("signals_supported_symbols", mode="before")
    @classmethod
    def validate_signals_supported_symbols(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=True)

    @field_validator("alpha_feature_timeframes", mode="before")
    @classmethod
    def validate_alpha_feature_timeframes(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=False)

    @field_validator("optimization_default_symbols", mode="before")
    @classmethod
    def validate_optimization_default_symbols(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=True)

    @field_validator("live_allowed_phases", mode="before")
    @classmethod
    def validate_live_allowed_phases(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=False)

    @field_validator("event_news_feed_urls", mode="before")
    @classmethod
    def validate_event_news_feed_urls(cls, value: str | list[str] | tuple[str, ...]) -> list[str]:
        return _split_csv(value, upper=False)

    @field_validator(
        "signals_regime_timeframe",
        "signals_setup_timeframe",
        "signals_trigger_timeframe",
        "live_phase_default",
        "portfolio_ranking_mode",
        "portfolio_correlation_mode",
        "polymarket_provider",
        "polymarket_provider_mode",
        "wallet_provider",
        "wallet_provider_mode",
        "wallet_signal_mode",
        "event_provider",
        "event_provider_mode",
        "replay_default_fidelity",
        "incident_alert_min_severity",
        mode="before",
    )
    @classmethod
    def validate_signal_timeframes(cls, value: str) -> str:
        return str(value).strip().lower()

    @model_validator(mode="after")
    def normalize_provider_modes(self) -> "Settings":
        provider_pairs = (
            ("polymarket_provider", "polymarket_provider_mode"),
            ("wallet_provider", "wallet_provider_mode"),
            ("event_provider", "event_provider_mode"),
        )
        for legacy_field, mode_field in provider_pairs:
            legacy_value = str(getattr(self, legacy_field)).strip().lower()
            mode_value = str(getattr(self, mode_field)).strip().lower()
            normalized = legacy_value if mode_value == "mock" and legacy_value != "mock" else mode_value
            setattr(self, legacy_field, normalized)
            setattr(self, mode_field, normalized)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

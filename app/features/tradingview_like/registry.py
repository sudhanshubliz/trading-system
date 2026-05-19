from __future__ import annotations

from app.features.tradingview_like.types import FeatureCatalogEntry


FEATURE_CATALOG: tuple[FeatureCatalogEntry, ...] = (
    FeatureCatalogEntry("ema_fast", "trend", "Fast exponential moving average.", "float"),
    FeatureCatalogEntry("ema_slow", "trend", "Slow exponential moving average.", "float"),
    FeatureCatalogEntry("sma_fast", "trend", "Fast simple moving average.", "float"),
    FeatureCatalogEntry("sma_slow", "trend", "Slow simple moving average.", "float"),
    FeatureCatalogEntry("rsi", "momentum", "Relative strength index.", "float"),
    FeatureCatalogEntry("macd", "momentum", "Moving-average convergence divergence line.", "float"),
    FeatureCatalogEntry("macd_signal", "momentum", "MACD signal line.", "float"),
    FeatureCatalogEntry("macd_hist", "momentum", "MACD histogram.", "float"),
    FeatureCatalogEntry("atr", "volatility", "Average true range.", "float"),
    FeatureCatalogEntry("atr_pct", "volatility", "ATR as a percent of price.", "float"),
    FeatureCatalogEntry("vwap", "trend", "Volume weighted average price.", "float"),
    FeatureCatalogEntry("vwap_gap_bps", "trend", "Distance from VWAP in basis points.", "float"),
    FeatureCatalogEntry("donchian_upper", "breakout", "Donchian upper band.", "float"),
    FeatureCatalogEntry("donchian_lower", "breakout", "Donchian lower band.", "float"),
    FeatureCatalogEntry("donchian_mid", "breakout", "Donchian midpoint.", "float"),
    FeatureCatalogEntry("bollinger_upper", "volatility", "Bollinger upper band.", "float"),
    FeatureCatalogEntry("bollinger_lower", "volatility", "Bollinger lower band.", "float"),
    FeatureCatalogEntry("bollinger_mid", "volatility", "Bollinger middle band.", "float"),
    FeatureCatalogEntry("bollinger_width_pct", "volatility", "Bollinger band width as percent.", "float"),
    FeatureCatalogEntry("keltner_upper", "volatility", "Keltner upper band.", "float"),
    FeatureCatalogEntry("keltner_lower", "volatility", "Keltner lower band.", "float"),
    FeatureCatalogEntry("keltner_mid", "volatility", "Keltner middle band.", "float"),
    FeatureCatalogEntry("keltner_width_pct", "volatility", "Keltner channel width as percent.", "float"),
    FeatureCatalogEntry("squeeze_on", "volatility", "Bollinger bands are inside Keltner channel.", "bool"),
    FeatureCatalogEntry("range_compression_pct", "breakout", "Normalized recent range compression.", "float"),
    FeatureCatalogEntry("breakout_bias", "breakout", "Directional position in breakout window.", "float"),
    FeatureCatalogEntry("market_structure", "structure", "Simple market structure classification.", "string"),
    FeatureCatalogEntry("order_block_hint", "structure", "Research placeholder for order-block context.", "string"),
    FeatureCatalogEntry("fvg_hint", "structure", "Research placeholder for fair-value gap context.", "string"),
    FeatureCatalogEntry("volume_ratio", "flow", "Current volume versus trailing average.", "float"),
)

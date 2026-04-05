from __future__ import annotations

import math

from app.live.types import LiveLockType


def safe_float(value: float | int | None) -> float:
    if value is None:
        return 0.0
    numeric = float(value)
    if not math.isfinite(numeric):
        return 0.0
    return round(numeric, 8)


def validate_side(side: str) -> bool:
    return side.lower() in {"buy", "sell", "long", "short"}


def normalize_order_side(side: str) -> str:
    lowered = side.lower()
    if lowered == "long":
        return "BUY"
    if lowered == "short":
        return "SELL"
    return lowered.upper()


def validate_order_request(
    *,
    symbol: str,
    side: str,
    quantity: float,
    order_type: str,
    notional: float,
    max_order_notional: float,
    limit_price: float | None,
    allow_market_orders: bool,
    allow_limit_orders: bool,
) -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    if not symbol or not symbol.isalnum():
        failures.append((LiveLockType.ORDER_VALIDATION_FAILED, "invalid_symbol"))
    if not validate_side(side):
        failures.append((LiveLockType.ORDER_VALIDATION_FAILED, "invalid_side"))
    if safe_float(quantity) <= 0:
        failures.append((LiveLockType.ORDER_VALIDATION_FAILED, "quantity_must_be_positive"))

    normalized_type = order_type.upper()
    if normalized_type == "MARKET" and not allow_market_orders:
        failures.append((LiveLockType.ORDER_VALIDATION_FAILED, "market_orders_disabled"))
    if normalized_type == "LIMIT" and not allow_limit_orders:
        failures.append((LiveLockType.ORDER_VALIDATION_FAILED, "limit_orders_disabled"))
    if normalized_type == "LIMIT" and safe_float(limit_price) <= 0:
        failures.append((LiveLockType.ORDER_VALIDATION_FAILED, "limit_price_required"))
    if safe_float(notional) <= 0:
        failures.append((LiveLockType.ORDER_VALIDATION_FAILED, "notional_must_be_positive"))
    if safe_float(notional) > safe_float(max_order_notional):
        failures.append((LiveLockType.ORDER_VALIDATION_FAILED, "order_notional_exceeds_limit"))
    return failures


def validate_market_freshness(*, age_seconds: float | None, stale_threshold_seconds: int) -> tuple[bool, str | None]:
    if age_seconds is None:
        return False, "market_data_missing"
    if safe_float(age_seconds) > float(stale_threshold_seconds):
        return False, "market_data_stale"
    return True, None


def check_loss_limit(*, pnl_pct: float, max_loss_pct: float) -> bool:
    return abs(min(pnl_pct, 0.0)) >= max_loss_pct


def check_open_risk_limit(*, open_risk_pct: float, max_open_risk_pct: float) -> bool:
    return safe_float(open_risk_pct) > safe_float(max_open_risk_pct)


def check_open_position_limit(*, open_positions: int, max_open_positions: int) -> bool:
    return int(open_positions) >= int(max_open_positions)


def check_consecutive_losses(*, consecutive_losses: int, max_consecutive_losses: int) -> bool:
    return int(consecutive_losses) >= int(max_consecutive_losses)

from __future__ import annotations

import math


def calculate_risk_amount(account_balance: float, max_risk_pct: float) -> float:
    if account_balance <= 0 or max_risk_pct <= 0:
        return 0.0
    return account_balance * (max_risk_pct / 100)


def calculate_stop_distance_abs(entry_price: float, stop_loss: float) -> float:
    if entry_price <= 0 or stop_loss <= 0:
        return 0.0
    return abs(entry_price - stop_loss)


def calculate_stop_distance_pct(entry_price: float, stop_loss: float) -> float:
    if entry_price <= 0:
        return 0.0
    return (calculate_stop_distance_abs(entry_price, stop_loss) / entry_price) * 100


def calculate_position_size(
    risk_amount: float,
    stop_distance_abs: float,
    precision: int = 6,
) -> float | None:
    if risk_amount <= 0 or stop_distance_abs <= 0:
        return None
    return round(risk_amount / stop_distance_abs, precision)


def cap_position_size_by_notional(
    entry_price: float,
    position_size: float | None,
    max_notional_value: float,
    *,
    precision: int = 6,
) -> float | None:
    if entry_price <= 0 or position_size is None or position_size <= 0 or max_notional_value <= 0:
        return position_size

    current_notional = calculate_notional_value(entry_price, position_size)
    if current_notional <= max_notional_value:
        return position_size

    scale = 10**precision
    capped_size = math.floor((max_notional_value / entry_price) * scale) / scale
    return round(capped_size, precision)


def calculate_notional_value(entry_price: float, position_size: float) -> float:
    if entry_price <= 0 or position_size <= 0:
        return 0.0
    return entry_price * position_size


def calculate_reward_risk_ratio(
    entry_price: float,
    stop_loss: float,
    target_1: float,
    side: str,
) -> float | None:
    if entry_price <= 0 or stop_loss <= 0 or target_1 <= 0:
        return None

    normalized_side = side.lower()
    if normalized_side == "long":
        risk = entry_price - stop_loss
        reward = target_1 - entry_price
    elif normalized_side == "short":
        risk = stop_loss - entry_price
        reward = entry_price - target_1
    else:
        return None

    if risk <= 0:
        return None

    return reward / risk

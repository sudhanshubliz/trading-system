from __future__ import annotations

from dataclasses import dataclass

from app.execution.types import Position


@dataclass(slots=True)
class ShadowComparison:
    symbol: str
    intended_entry: float
    current_price: float
    movement_pct: float
    note: str


def compare_position(position: Position) -> ShadowComparison:
    entry = position.entry_price
    current = position.current_price
    movement_pct = ((current - entry) / entry * 100.0) if entry > 0 else 0.0
    note = f"shadow movement {movement_pct:.2f}% from intended entry"
    return ShadowComparison(
        symbol=position.symbol,
        intended_entry=entry,
        current_price=current,
        movement_pct=round(movement_pct, 4),
        note=note,
    )

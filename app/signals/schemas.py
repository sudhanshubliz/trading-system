from __future__ import annotations


def normalize_requested_symbols(symbols: list[str] | None) -> list[str] | None:
    if symbols is None:
        return None
    return [symbol.upper() for symbol in symbols if symbol.strip()]

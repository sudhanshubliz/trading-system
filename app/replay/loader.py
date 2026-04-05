from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.market_data.types import Candle


def load_replay_candles(source: str | dict[str, Any] | list[dict[str, Any]]) -> dict[str, dict[str, list[Candle]]]:
    if isinstance(source, str):
        return _load_from_path(Path(source))
    if isinstance(source, list):
        return _load_from_flat_rows(source)
    if isinstance(source, dict):
        return _load_from_nested_mapping(source)
    return {}


def load_candles_from_file(path: str | Path) -> list[Candle]:
    resolved_path = Path(path)
    if not resolved_path.exists():
        return []

    if resolved_path.suffix.lower() == ".json":
        payload = json.loads(resolved_path.read_text())
        if isinstance(payload, list):
            candles = [_to_candle(item) for item in payload]
            return [candle for candle in candles if candle is not None]
        normalized = load_replay_candles(payload)
        return _flatten_candles(normalized)

    if resolved_path.suffix.lower() == ".csv":
        with resolved_path.open("r", newline="") as handle:
            reader = csv.DictReader(handle)
            candles = [_to_candle(row) for row in reader]
            return [candle for candle in candles if candle is not None]

    return []


def slice_replay_candles(
    candles: dict[str, dict[str, list[Candle]]],
    *,
    symbols: list[str] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    max_bars: int | None = None,
) -> dict[str, dict[str, list[Candle]]]:
    allowed_symbols = {symbol.upper() for symbol in symbols} if symbols else None
    sliced: dict[str, dict[str, list[Candle]]] = {}

    for symbol, timeframes in candles.items():
        normalized_symbol = symbol.upper()
        if allowed_symbols is not None and normalized_symbol not in allowed_symbols:
            continue

        sliced_timeframes: dict[str, list[Candle]] = {}
        for timeframe, series in timeframes.items():
            filtered = [
                candle
                for candle in series
                if (start_time is None or candle.open_time >= start_time)
                and (end_time is None or candle.open_time <= end_time)
            ]
            if max_bars is not None and max_bars > 0:
                filtered = filtered[-max_bars:]
            sliced_timeframes[timeframe.lower()] = filtered

        sliced[normalized_symbol] = sliced_timeframes

    return sliced


def _load_from_path(path: Path) -> dict[str, dict[str, list[Candle]]]:
    if not path.exists():
        return {}
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text())
        return load_replay_candles(payload)
    if path.suffix.lower() == ".csv":
        with path.open("r", newline="") as handle:
            reader = csv.DictReader(handle)
            return _load_from_flat_rows(list(reader))
    return {}


def _load_from_flat_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[Candle]]]:
    store: dict[str, dict[str, list[Candle]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        timeframe = str(row.get("timeframe", "")).lower()
        if not symbol or not timeframe:
            continue
        candle = _to_candle(row)
        if candle is None:
            continue
        store[symbol][timeframe].append(candle)
    return _finalize_store(store)


def _load_from_nested_mapping(payload: dict[str, Any]) -> dict[str, dict[str, list[Candle]]]:
    store: dict[str, dict[str, list[Candle]]] = defaultdict(lambda: defaultdict(list))
    for symbol, timeframes in payload.items():
        if not isinstance(timeframes, dict):
            continue
        normalized_symbol = str(symbol).upper()
        for timeframe, raw_candles in timeframes.items():
            normalized_timeframe = str(timeframe).lower()
            if not isinstance(raw_candles, list):
                continue
            for raw_candle in raw_candles:
                candle = _to_candle(raw_candle)
                if candle is None:
                    continue
                store[normalized_symbol][normalized_timeframe].append(candle)
    return _finalize_store(store)


def _to_candle(raw: dict[str, Any]) -> Candle | None:
    if isinstance(raw, Candle):
        if not raw.is_closed:
            return None
        return Candle(
            open_time=raw.open_time,
            open=raw.open,
            high=raw.high,
            low=raw.low,
            close=raw.close,
            volume=raw.volume,
            is_closed=True,
        )

    try:
        open_time = raw.get("open_time")
        if isinstance(open_time, str):
            parsed_time = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
        elif isinstance(open_time, datetime):
            parsed_time = open_time
        else:
            return None

        is_closed = bool(raw.get("is_closed", True))
        if not is_closed:
            return None

        return Candle(
            open_time=parsed_time,
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=float(raw["volume"]),
            is_closed=True,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _finalize_store(
    store: dict[str, dict[str, list[Candle]]],
) -> dict[str, dict[str, list[Candle]]]:
    finalized: dict[str, dict[str, list[Candle]]] = {}
    for symbol, timeframes in store.items():
        finalized[symbol] = {}
        for timeframe, candles in timeframes.items():
            finalized[symbol][timeframe] = sorted(candles, key=lambda candle: candle.open_time)
    return finalized


def _flatten_candles(candles: dict[str, dict[str, list[Candle]]]) -> list[Candle]:
    flattened: list[Candle] = []
    for timeframes in candles.values():
        for series in timeframes.values():
            flattened.extend(series)
    flattened.sort(key=lambda candle: candle.open_time)
    return flattened

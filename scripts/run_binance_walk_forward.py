#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import get_settings  # noqa: E402
from app.market_data.types import Candle  # noqa: E402
from app.replay.service import ReplayService  # noqa: E402


SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"
FUTURES_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run cost-aware Binance walk-forward replay using public candles.")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--initial-balance", type=float, default=5000.0)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--end", help="UTC ISO timestamp; defaults to the latest completed five-minute boundary")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def fetch_klines(
    base_url: str,
    *,
    symbol: str,
    timeframe: str,
    start_time: datetime,
    end_time: datetime,
) -> list[Candle]:
    cursor = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    rows: dict[int, list[object]] = {}
    while cursor < end_ms:
        query = urlencode(
            {
                "symbol": symbol,
                "interval": timeframe,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        request = Request(f"{base_url}?{query}", headers={"User-Agent": "trading-system-walk-forward/1.0"})
        with urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not batch:
            break
        for row in batch:
            timestamp = int(row[0])
            if timestamp < end_ms:
                rows[timestamp] = row
        next_cursor = int(batch[-1][0]) + 1
        if next_cursor <= cursor or len(batch) < 1000:
            break
        cursor = next_cursor
    return [
        Candle(
            open_time=datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            is_closed=True,
        )
        for timestamp, row in sorted(rows.items())
    ]


def latest_completed_boundary() -> datetime:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return now - timedelta(minutes=now.minute % 5)


async def run(args: argparse.Namespace) -> tuple[dict[str, object], Path]:
    settings = get_settings()
    if args.days < settings.replay_walk_forward_min_days:
        raise ValueError(f"days must be at least {settings.replay_walk_forward_min_days}")
    end_time = datetime.fromisoformat(args.end.replace("Z", "+00:00")) if args.end else latest_completed_boundary()
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    start_time = end_time - timedelta(days=args.days)
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    timeframes = ["5m", "15m", "1h"]
    spot = {
        symbol: {
            timeframe: fetch_klines(
                SPOT_KLINES_URL,
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_time,
                end_time=end_time,
            )
            for timeframe in timeframes
        }
        for symbol in symbols
    }
    futures = {
        symbol: {
            timeframe: fetch_klines(
                FUTURES_KLINES_URL,
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_time,
                end_time=end_time,
            )
            for timeframe in timeframes
        }
        for symbol in symbols
    }
    service = ReplayService(settings=settings)
    replay, report = await service.run_walk_forward(
        candles_source=spot,
        futures_candles_source=futures,
        symbols=symbols,
        initial_balance=args.initial_balance,
        start_time=start_time,
        end_time=end_time,
        fold_count=args.folds,
        fidelity_mode="high_fidelity_best_effort",
    )
    metrics = replay.metrics
    artifact = {
        "report": asdict(report),
        "replay": {
            "run_id": replay.run_id,
            "status": replay.status,
            "initial_balance": replay.initial_balance,
            "total_steps": replay.total_steps,
            "metrics": {
                "total_trades": metrics.total_trades if metrics else 0,
                "realized_pnl_total": metrics.realized_pnl_total if metrics else 0.0,
                "gross_realized_pnl_total": metrics.gross_realized_pnl_total if metrics else 0.0,
                "fees_paid_total": metrics.fees_paid_total if metrics else 0.0,
                "slippage_cost_total": metrics.slippage_cost_total if metrics else 0.0,
                "turnover_notional": metrics.turnover_notional if metrics else 0.0,
                "ending_balance": metrics.ending_balance if metrics else replay.initial_balance,
            },
            "fidelity_notes": replay.fidelity_notes,
        },
        "data_counts": {
            "spot": {symbol: {timeframe: len(spot[symbol][timeframe]) for timeframe in timeframes} for symbol in symbols},
            "futures": {symbol: {timeframe: len(futures[symbol][timeframe]) for timeframe in timeframes} for symbol in symbols},
        },
    }
    output = args.output or ROOT / "artifacts" / "replay" / f"walk_forward_{end_time:%Y%m%dT%H%M%SZ}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, default=str) + "\n", encoding="utf-8")
    return artifact, output


def main() -> int:
    args = parse_args()
    try:
        artifact, output = asyncio.run(run(args))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    report = artifact["report"]
    print(
        json.dumps(
            {
                "status": "completed",
                "passed": report["passed"],
                "blockers": report["blockers"],
                "net_pnl": report["net_pnl"],
                "expectancy": report["expectancy"],
                "positive_folds": report["positive_fold_count"],
                "fold_count": report["fold_count"],
                "artifact": str(output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

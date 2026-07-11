from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(slots=True)
class EndpointResult:
    name: str
    ok: bool
    status_code: int | None
    payload: Any | None = None
    error: str | None = None


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 10,
) -> EndpointResult:
    url = f"{base_url.rstrip('/')}{path}"
    if params:
        query = urlencode({key: value for key, value in params.items() if value is not None}, doseq=True)
        url = f"{url}?{query}"

    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
            parsed = json.loads(raw_body) if raw_body else None
            return EndpointResult(
                name=path,
                ok=True,
                status_code=response.status,
                payload=parsed,
            )
    except HTTPError as exc:
        try:
            raw_body = exc.read().decode("utf-8")
            parsed = json.loads(raw_body) if raw_body else None
        except Exception:
            parsed = None
        return EndpointResult(
            name=path,
            ok=False,
            status_code=exc.code,
            payload=parsed,
            error=f"http_error:{exc.code}",
        )
    except (URLError, TimeoutError, OSError) as exc:
        return EndpointResult(
            name=path,
            ok=False,
            status_code=None,
            error=repr(exc),
        )


def _compact_signal(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": signal.get("signal_id"),
        "symbol": signal.get("symbol"),
        "side": signal.get("side"),
        "strategy_name": signal.get("strategy_name"),
        "confidence_score": signal.get("confidence_score"),
        "entry_price": signal.get("entry_price"),
        "generated_at": signal.get("generated_at"),
    }


def _compact_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "assessment_id": assessment.get("assessment_id"),
        "signal_id": assessment.get("signal_id"),
        "symbol": assessment.get("symbol"),
        "side": assessment.get("side"),
        "strategy_name": assessment.get("strategy_name"),
        "final_decision": assessment.get("final_decision"),
        "notional_value": assessment.get("notional_value"),
        "risk_amount": assessment.get("risk_amount"),
        "rejection_reasons": assessment.get("rejection_reasons"),
    }


def _compact_trade(trade: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_id": trade.get("trade_id"),
        "symbol": trade.get("symbol"),
        "side": trade.get("side"),
        "strategy_name": trade.get("strategy_name"),
        "execution_mode": trade.get("execution_mode"),
        "status": trade.get("status"),
        "opened_at": trade.get("opened_at"),
    }


def build_report(
    *,
    base_url: str,
    symbols: list[str],
    ensure_shadow_running: bool,
    include_signal_evaluation: bool,
) -> dict[str, Any]:
    results: dict[str, EndpointResult] = {}
    results["health"] = _request_json(base_url, "/health")
    results["readyz"] = _request_json(base_url, "/health/readyz")
    results["market_data_health"] = _request_json(base_url, "/market-data/health")
    results["risk_summary"] = _request_json(base_url, "/risk/summary")
    results["risk_locks"] = _request_json(base_url, "/risk/locks/current")
    results["provider_health_summary"] = _request_json(base_url, "/provider-health/summary")
    results["system_summary"] = _request_json(base_url, "/system/intelligence/summary")

    if ensure_shadow_running:
        start_result = _request_json(base_url, "/shadow/start", method="POST", payload={})
        results["shadow_start"] = start_result
    results["shadow_status"] = _request_json(base_url, "/shadow/status")

    if include_signal_evaluation:
        signal_payload = {"symbols": symbols}
        results["signals_eval"] = _request_json(
            base_url,
            "/signals/evaluate",
            method="POST",
            payload=signal_payload,
        )
        results["risk_eval"] = _request_json(
            base_url,
            "/risk/evaluate-signals",
            method="POST",
            payload=signal_payload,
        )

    results["signals_cached"] = _request_json(base_url, "/signals", params={"limit": 10})
    results["approvals"] = _request_json(base_url, "/approvals/pending")
    results["trades"] = _request_json(base_url, "/trades")
    results["execution_quality"] = _request_json(base_url, "/execution/quality", params={"limit": 10})

    health_payload = results["health"].payload if isinstance(results["health"].payload, dict) else {}
    ready_payload = results["readyz"].payload if isinstance(results["readyz"].payload, dict) else {}
    market_data_payload = (
        results["market_data_health"].payload if isinstance(results["market_data_health"].payload, dict) else {}
    )
    shadow_payload = results["shadow_status"].payload if isinstance(results["shadow_status"].payload, dict) else {}
    approvals_payload = results["approvals"].payload if isinstance(results["approvals"].payload, dict) else {}
    trades_payload = results["trades"].payload if isinstance(results["trades"].payload, dict) else {}
    execution_quality_payload = (
        results["execution_quality"].payload if isinstance(results["execution_quality"].payload, dict) else {}
    )
    signals_eval_payload = (
        results.get("signals_eval").payload
        if include_signal_evaluation and isinstance(results.get("signals_eval").payload, dict)
        else {}
    )
    risk_eval_payload = (
        results.get("risk_eval").payload
        if include_signal_evaluation and isinstance(results.get("risk_eval").payload, dict)
        else {}
    )
    signals_cached_payload = (
        results["signals_cached"].payload if isinstance(results["signals_cached"].payload, dict) else {}
    )
    risk_locks_payload = results["risk_locks"].payload if isinstance(results["risk_locks"].payload, dict) else {}

    errors = [
        {"name": name, "error": result.error, "status_code": result.status_code}
        for name, result in results.items()
        if not result.ok
    ]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "symbols": symbols,
        "health_status": health_payload.get("status"),
        "ready": ready_payload.get("ready"),
        "trading_mode": health_payload.get("mode"),
        "global_pause": health_payload.get("global_pause"),
        "market_data_status": market_data_payload.get("status"),
        "websocket_status": market_data_payload.get("websocket_status"),
        "shadow_running": shadow_payload.get("running"),
        "shadow_last_cycle_at": shadow_payload.get("last_cycle_at"),
        "signals_eval_count": signals_eval_payload.get("count"),
        "risk_eval_count": risk_eval_payload.get("count"),
        "cached_signals_count": signals_cached_payload.get("count"),
        "risk_locks_count": risk_locks_payload.get("count"),
        "pending_approvals_count": approvals_payload.get("count"),
        "trades_count": trades_payload.get("count"),
        "execution_quality_count": execution_quality_payload.get("count"),
        "errors": errors,
    }

    return {
        "summary": summary,
        "samples": {
            "signals_eval": [_compact_signal(item) for item in signals_eval_payload.get("items", [])[:3]],
            "risk_eval": [_compact_assessment(item) for item in risk_eval_payload.get("items", [])[:3]],
            "cached_signals": [_compact_signal(item) for item in signals_cached_payload.get("items", [])[:3]],
            "trades": [_compact_trade(item) for item in trades_payload.get("items", [])[:3]],
        },
        "raw": {name: result.payload for name, result in results.items() if result.ok},
        "errors": errors,
    }


def print_human_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("Daily Operator Check")
    print(f"Generated At: {summary['generated_at']}")
    print(f"Base URL: {summary['base_url']}")
    print()
    print("Core Status")
    print(f"- Health: {summary['health_status']}")
    print(f"- Ready: {summary['ready']}")
    print(f"- Trading Mode: {summary['trading_mode']}")
    print(f"- Global Pause: {summary['global_pause']}")
    print(f"- Market Data: {summary['market_data_status']} (ws={summary['websocket_status']})")
    print(f"- Shadow Running: {summary['shadow_running']}")
    print(f"- Shadow Last Cycle: {summary['shadow_last_cycle_at']}")
    print()
    print("Pipeline Counts")
    print(f"- Signals Evaluated: {summary['signals_eval_count']}")
    print(f"- Risk Assessments: {summary['risk_eval_count']}")
    print(f"- Cached Signals: {summary['cached_signals_count']}")
    print(f"- Active Risk Locks: {summary['risk_locks_count']}")
    print(f"- Pending Approvals: {summary['pending_approvals_count']}")
    print(f"- Trades: {summary['trades_count']}")
    print(f"- Execution Quality Records: {summary['execution_quality_count']}")

    for section in ("signals_eval", "risk_eval", "cached_signals", "trades"):
        items = report["samples"][section]
        if not items:
            continue
        print()
        print(f"{section}:")
        for item in items:
            print(f"- {json.dumps(item, default=str)}")

    if report["errors"]:
        print()
        print("Errors:")
        for item in report["errors"]:
            print(f"- {item['name']}: {item['error']} (status={item['status_code']})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily operator health and trading pipeline check.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:3030/api/v1",
        help="Backend API base URL.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        help="Symbols to use for signal and risk evaluation checks.",
    )
    parser.add_argument(
        "--ensure-shadow-running",
        action="store_true",
        help="Start shadow mode before collecting the report.",
    )
    parser.add_argument(
        "--skip-signal-eval",
        action="store_true",
        help="Skip the live signal and risk evaluation calls.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to write the full JSON report.",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit non-zero if core health, readiness, market data, or shadow state is unhealthy.",
    )
    args = parser.parse_args()

    report = build_report(
        base_url=args.base_url,
        symbols=[symbol.upper() for symbol in args.symbols],
        ensure_shadow_running=args.ensure_shadow_running,
        include_signal_evaluation=not args.skip_signal_eval,
    )
    print_human_report(report)

    if args.json_out:
        output_path = Path(args.json_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, default=str, indent=2))
        print()
        print(f"JSON report written to {output_path}")

    if not args.fail_on_warning:
        return 0

    summary = report["summary"]
    problems = [
        summary["health_status"] != "healthy",
        summary["ready"] is not True,
        summary["market_data_status"] != "ok",
        summary["shadow_running"] is not True,
        bool(report["errors"]),
    ]
    return 1 if any(problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())

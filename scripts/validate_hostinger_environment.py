from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit


REQUIRED_SECRETS = {
    "SECRET_KEY": 32,
    "LLM_API_KEY": 16,
    "ZEP_API_KEY": 16,
}


def validate_environment(values: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    for name, minimum_length in REQUIRED_SECRETS.items():
        value = values.get(name, "").strip()
        if not value:
            errors.append(f"{name}:missing")
        elif _is_placeholder(value):
            errors.append(f"{name}:placeholder")
        elif len(value) < minimum_length:
            errors.append(f"{name}:too_short")

    model_name = values.get("LLM_MODEL_NAME", "").strip()
    if not model_name:
        errors.append("LLM_MODEL_NAME:missing")
    elif _is_placeholder(model_name):
        errors.append("LLM_MODEL_NAME:placeholder")

    base_url = values.get("LLM_BASE_URL", "").strip()
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        errors.append("LLM_BASE_URL:invalid")
    elif parsed.hostname.endswith(".example") or parsed.hostname == "example.com":
        errors.append("LLM_BASE_URL:placeholder")

    expected_values = {
        "TRADING_MODE": "paper",
        "EXECUTION_MODE": "paper",
        "ENABLE_LIVE_TRADING": "false",
        "LIVE_TRADING_ARMED": "false",
        "LIVE_EXECUTION_MODE": "paper",
        "ENABLE_MIROFISH": "true",
        "MIROFISH_PROVIDER": "external",
    }
    for name, expected in expected_values.items():
        actual = values.get(name, "").strip().lower()
        if actual != expected:
            errors.append(f"{name}:expected_{expected}")
    return errors


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("replace_") or "your-" in lowered or "your_" in lowered


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Hostinger configuration without printing secrets.")
    parser.add_argument("--environment", action="store_true", help="Read values from the process environment.")
    parser.add_argument(
        "--mirofish-env-file",
        type=Path,
        default=Path("deploy/hostinger/mirofish.env"),
    )
    parser.add_argument(
        "--trading-env-file",
        type=Path,
        default=Path("deploy/hostinger/trading-system.env"),
    )
    args = parser.parse_args()

    if args.environment:
        values = dict(os.environ)
        source = "environment"
    else:
        try:
            values = load_env_file(args.mirofish_env_file)
            values.update(load_env_file(args.trading_env_file))
        except OSError as exc:
            print(json.dumps({"status": "failed", "errors": [f"env_file:{type(exc).__name__}"]}))
            return 1
        source = "env_files"

    errors = validate_environment(values)
    print(
        json.dumps(
            {
                "status": "passed" if not errors else "failed",
                "source": source,
                "errors": errors,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

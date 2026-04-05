from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings, get_settings
from app.persistence.models import PersistenceBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def safe_float(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(numeric):
        return 0.0
    return round(numeric, 8)


def sanitize_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, datetime):
        aware = ensure_aware_datetime(value)
        return aware.isoformat() if aware is not None else None
    if isinstance(value, float):
        return safe_float(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        return value
    if is_dataclass(value):
        return sanitize_value(asdict(value))
    if hasattr(value, "model_dump"):
        return sanitize_value(value.model_dump())
    if isinstance(value, dict):
        return {str(key): sanitize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_value(item) for item in value]
    return str(value)


def serialize_payload(value: Any) -> str:
    return json.dumps(sanitize_value(value), sort_keys=True, separators=(",", ":"))


def deserialize_payload(payload_json: str | None) -> Any:
    if not payload_json:
        return {}
    return json.loads(payload_json)


@lru_cache(maxsize=8)
def get_persistence_engine(db_url: str | None = None) -> Engine:
    settings = get_settings()
    resolved_url = db_url or settings.persistence_db_url
    connect_args = {"check_same_thread": False} if resolved_url.startswith("sqlite") else {}
    return create_engine(resolved_url, future=True, connect_args=connect_args)


@lru_cache(maxsize=8)
def get_persistence_session_factory(db_url: str | None = None) -> sessionmaker[Session]:
    engine = get_persistence_engine(db_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)


def init_persistence_db(settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    engine = get_persistence_engine(resolved_settings.persistence_db_url)
    PersistenceBase.metadata.create_all(bind=engine)
    _ensure_sqlite_schema(engine)


def _ensure_sqlite_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    required_columns: dict[str, dict[str, str]] = {
        "persisted_approvals": {
            "execution_mode": "VARCHAR(32) DEFAULT 'paper'",
        },
        "persisted_trades": {
            "execution_mode": "VARCHAR(32) DEFAULT 'paper'",
            "client_order_id": "VARCHAR(64)",
            "exchange_order_id": "VARCHAR(64)",
            "exchange_status": "VARCHAR(64)",
            "reconciliation_status": "VARCHAR(64)",
            "last_reconciled_at": "DATETIME",
        },
        "persisted_positions": {
            "execution_mode": "VARCHAR(32) DEFAULT 'paper'",
            "reconciliation_status": "VARCHAR(64)",
            "last_reconciled_at": "DATETIME",
        },
        "persisted_events": {
            "execution_mode": "VARCHAR(32)",
        },
    }

    with engine.begin() as connection:
        for table_name, columns in required_columns.items():
            existing_tables = {
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                    (table_name,),
                )
            }
            if table_name not in existing_tables:
                continue

            current_columns = {
                str(row[1])
                for row in connection.exec_driver_sql(f"PRAGMA table_info('{table_name}')").fetchall()
            }
            for column_name, column_type in columns.items():
                if column_name in current_columns:
                    continue
                connection.exec_driver_sql(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                )

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings
from app.db.base import Base
from app.db.models import MarketSnapshot, SystemState

settings = get_settings()

sqlite_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=sqlite_connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_system_state(session: Session) -> None:
    defaults = {
        "trading_mode": {"mode": "paper"},
        "global_pause": {"paused": settings.global_pause},
        "live_trading": {"armed": False, "reason": "default_disarmed"},
    }

    created = False
    for key, value in defaults.items():
        if session.get(SystemState, key) is None:
            session.add(
                SystemState(
                    key=key,
                    value_json=json.dumps(value),
                    updated_at=utc_now(),
                )
            )
            created = True

    if created:
        session.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed_system_state(session)

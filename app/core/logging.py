from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.persistence.db import sanitize_value


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


def configure_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    formatter = UTCFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)


def log_structured_event(logger: logging.Logger, event_type: str, **payload: Any) -> None:
    body = {"event_type": event_type, **sanitize_value(payload)}
    logger.info(json.dumps(body, sort_keys=True, separators=(",", ":")))

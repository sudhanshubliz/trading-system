from __future__ import annotations

import json

from app.config.settings import get_settings
from app.db.session import init_db
from app.persistence.db import init_persistence_db


def main() -> None:
    settings = get_settings()
    init_db()
    if settings.persistence_enabled:
        init_persistence_db(settings)
    print(
        json.dumps(
            {
                "status": "ok",
                "database_url": settings.database_url,
                "persistence_enabled": settings.persistence_enabled,
                "persistence_db_url": settings.persistence_db_url,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

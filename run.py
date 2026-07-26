from __future__ import annotations

import os

import uvicorn

from emotionos.app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.auto_migrate:
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
    uvicorn.run(
        "emotionos.app.main:app",
        host=settings.app_host,
        port=int(os.getenv("DATABRICKS_APP_PORT", settings.app_port)),
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()

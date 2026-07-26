from __future__ import annotations

import os
from collections.abc import Callable, Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from emotionos.app.core.config import get_settings


def _lakebase_schema_name() -> str:
    configured = os.getenv("LAKEBASE_SCHEMA", "").strip()
    if configured:
        return configured

    app_name = os.getenv("PGAPPNAME", "emotionos").strip()
    client_id = os.getenv("DATABRICKS_CLIENT_ID", os.getenv("PGUSER", "")).strip()
    if not client_id:
        raise RuntimeError("Lakebase schema identity is missing")
    return f"{app_name}_schema_{client_id.replace('-', '')}"


def _lakebase_connection_creator() -> Callable[[], object]:
    required = ["PGHOST", "PGDATABASE", "PGUSER", "LAKEBASE_ENDPOINT_NAME"]
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError(f"Lakebase configuration is missing: {', '.join(missing)}")

    def connect():
        import psycopg
        from psycopg import sql
        from databricks.sdk import WorkspaceClient

        credential = WorkspaceClient().postgres.generate_database_credential(
            endpoint=os.environ["LAKEBASE_ENDPOINT_NAME"]
        )
        connection = psycopg.connect(
            host=os.environ["PGHOST"],
            port=os.getenv("PGPORT", "5432"),
            dbname=os.environ["PGDATABASE"],
            user=os.environ["PGUSER"],
            password=credential.token,
            sslmode=os.getenv("PGSSLMODE", "require"),
            application_name=os.getenv("PGAPPNAME", "emotionos"),
        )
        schema_name = _lakebase_schema_name()
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema_name))
            )
            cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        connection.commit()
        return connection

    return connect


def make_engine(database_url: str | None = None):
    settings = get_settings()
    if database_url is None and settings.database_backend == "lakebase":
        return create_engine(
            "postgresql+psycopg://",
            creator=_lakebase_connection_creator(),
            pool_pre_ping=True,
            pool_recycle=3000,
            future=True,
        )

    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

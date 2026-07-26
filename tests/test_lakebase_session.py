from __future__ import annotations

from emotionos.app.db.session import _lakebase_schema_name


def test_lakebase_schema_name_uses_app_identity(monkeypatch) -> None:
    monkeypatch.delenv("LAKEBASE_SCHEMA", raising=False)
    monkeypatch.setenv("PGAPPNAME", "emotionos-worlds")
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "a0f4864b-9c61-4e0e-8fc4-791b46cfe88b")

    assert (
        _lakebase_schema_name()
        == "emotionos-worlds_schema_a0f4864b9c614e0e8fc4791b46cfe88b"
    )


def test_lakebase_schema_name_accepts_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("LAKEBASE_SCHEMA", "rolebricks")

    assert _lakebase_schema_name() == "rolebricks"

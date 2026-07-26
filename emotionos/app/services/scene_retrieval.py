from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import ExternalProviderError, ProviderConfigurationError

logger = logging.getLogger(__name__)


class SceneRetriever(Protocol):
    provider_name: str

    async def retrieve(
        self,
        *,
        scene_id: uuid.UUID,
        character_key: str,
        query: str,
        current_memories: list[dict[str, Any]],
        current_sources: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...

    async def index(self, records: list[dict[str, Any]]) -> None: ...

    async def purge_scene(self, scene_id: uuid.UUID, *, layers: list[str] | None = None) -> None: ...


class DatabaseSceneRetriever:
    """Short-context retrieval for tests and explicit local development."""

    provider_name = "database"

    async def retrieve(
        self,
        *,
        scene_id: uuid.UUID,
        character_key: str,
        query: str,
        current_memories: list[dict[str, Any]],
        current_sources: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        del scene_id, character_key, query
        return current_memories[:8], current_sources[:10]

    async def index(self, records: list[dict[str, Any]]) -> None:
        del records

    async def purge_scene(self, scene_id: uuid.UUID, *, layers: list[str] | None = None) -> None:
        del scene_id, layers


class DatabricksAISearchRetriever:
    """Adds durable semantic recall to the current Lakebase scene context."""

    provider_name = "databricks"
    columns = [
        "record_id",
        "scene_id",
        "character_key",
        "record_type",
        "content",
        "title",
        "url",
        "freshness",
        "importance",
        "visibility",
    ]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def retrieve(
        self,
        *,
        scene_id: uuid.UUID,
        character_key: str,
        query: str,
        current_memories: list[dict[str, Any]],
        current_sources: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows = await self._query(scene_id=scene_id, query=query)
        indexed_memories: list[dict[str, Any]] = []
        indexed_sources: list[dict[str, Any]] = []
        for row in rows:
            row_character = str(row.get("character_key") or "")
            if row_character and row_character != character_key:
                continue
            if row.get("record_type") == "source":
                indexed_sources.append(
                    {
                        "id": str(row.get("record_id") or ""),
                        "title": str(row.get("title") or "Source"),
                        "url": str(row.get("url") or ""),
                        "snippet": str(row.get("content") or ""),
                        "freshness": str(row.get("freshness") or "stable"),
                    }
                )
            else:
                indexed_memories.append(
                    {
                        "layer": str(row.get("record_type") or "episode"),
                        "visibility": str(row.get("visibility") or "private"),
                        "content": str(row.get("content") or ""),
                        "importance": int(row.get("importance") or 0),
                    }
                )

        return (
            self._merge(current_memories, indexed_memories, key="content", limit=8),
            self._merge(current_sources, indexed_sources, key="id", limit=10),
        )

    async def index(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        if not self.settings.databricks_sql_warehouse_id.strip():
            raise ProviderConfigurationError(
                "Databricks memory indexing is not configured.",
                details={"missing": ["DATABRICKS_SQL_WAREHOUSE_ID"]},
            )
        identifiers = [self.settings.databricks_catalog, self.settings.databricks_schema]
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item) for item in identifiers):
            raise ProviderConfigurationError("Databricks catalog and schema must be simple SQL identifiers.")

        for start in range(0, len(records), 20):
            await self._merge_records(records[start : start + 20])
        try:
            await self._sync_index()
        except ExternalProviderError as exc:
            logger.warning(
                "Databricks AI Search sync deferred after durable memory write: %s",
                exc.details,
            )

    async def purge_scene(self, scene_id: uuid.UUID, *, layers: list[str] | None = None) -> None:
        if not self.settings.databricks_sql_warehouse_id.strip():
            return
        if layers:
            layer_values = ", ".join(f"'{layer}'" for layer in layers if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", layer))
            if not layer_values:
                return
            predicate = f"scene_id = :scene_id AND record_type IN ({layer_values})"
        else:
            predicate = "scene_id = :scene_id"
        table = f"{self.settings.databricks_catalog}.{self.settings.databricks_schema}.scene_memory_search"
        await self._execute_sql_statement(
            f"DELETE FROM {table} WHERE {predicate}",
            [{"name": "scene_id", "value": str(scene_id), "type": "STRING"}],
        )
        try:
            await self._sync_index()
        except ExternalProviderError as exc:
            logger.warning("Databricks AI Search sync deferred after scene purge: %s", exc.details)
    async def _sync_index(self) -> None:
        from databricks.sdk import WorkspaceClient

        workspace = WorkspaceClient()
        headers = dict(workspace.config.authenticate())
        headers["Content-Type"] = "application/json"
        host = (self.settings.databricks_host or workspace.config.host or "").rstrip("/")
        if host and "://" not in host:
            host = f"https://{host}"
        index_name = quote(self.settings.databricks_ai_search_index.strip(), safe="")
        try:
            async with httpx.AsyncClient(timeout=self.settings.databricks_timeout_seconds) as client:
                response = await client.post(
                    f"{host}/api/2.0/vector-search/indexes/{index_name}/sync",
                    headers=headers,
                    json={},
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExternalProviderError(
                "Databricks AI Search sync failed.",
                details={"status": exc.response.status_code, "response": exc.response.text[:1200]},
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalProviderError(
                "Databricks AI Search sync could not be started.",
                details={"reason": str(exc)},
            ) from exc

    async def _execute_sql_statement(self, statement: str, parameters: list[dict[str, Any]]) -> None:
        from databricks.sdk import WorkspaceClient

        try:
            workspace = WorkspaceClient()
            headers = dict(workspace.config.authenticate())
            host = (self.settings.databricks_host or workspace.config.host or "").rstrip("/")
            if host and "://" not in host:
                host = f"https://{host}"
        except Exception as exc:
            raise ProviderConfigurationError(
                "Databricks authentication failed while updating scene memory.",
                details={"provider": "databricks", "reason": str(exc)},
            ) from exc
        if not host:
            raise ProviderConfigurationError("DATABRICKS_HOST is missing.")
        payload = {
            "warehouse_id": self.settings.databricks_sql_warehouse_id,
            "catalog": self.settings.databricks_catalog,
            "schema": self.settings.databricks_schema,
            "statement": statement,
            "parameters": parameters,
            "wait_timeout": "30s",
            "on_wait_timeout": "CONTINUE",
        }
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=self.settings.databricks_timeout_seconds) as client:
            try:
                response = await client.post(f"{host}/api/2.0/sql/statements", headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                deadline = asyncio.get_running_loop().time() + self.settings.databricks_timeout_seconds
                while (result.get("status") or {}).get("state") in {"PENDING", "RUNNING"}:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise ExternalProviderError("Databricks memory update timed out.")
                    await asyncio.sleep(0.5)
                    response = await client.get(f"{host}/api/2.0/sql/statements/{result['statement_id']}", headers=headers)
                    response.raise_for_status()
                    result = response.json()
            except httpx.HTTPStatusError as exc:
                raise ExternalProviderError(
                    "Databricks memory update failed.",
                    details={"status": exc.response.status_code, "response": exc.response.text[:1200]},
                ) from exc
            except httpx.HTTPError as exc:
                raise ExternalProviderError(
                    "Databricks memory update could not be completed.",
                    details={"reason": str(exc)},
                ) from exc
        status = result.get("status") or {}
        if status.get("state") != "SUCCEEDED":
            raise ExternalProviderError("Databricks memory update did not succeed.", details={"status": status})
    async def _merge_records(self, records: list[dict[str, Any]]) -> None:
        from databricks.sdk import WorkspaceClient

        try:
            workspace = WorkspaceClient()
            headers = dict(workspace.config.authenticate())
            host = (self.settings.databricks_host or workspace.config.host or "").rstrip("/")
            if host and "://" not in host:
                host = f"https://{host}"
        except Exception as exc:
            raise ProviderConfigurationError(
                "Databricks authentication failed while indexing scene memory.",
                details={"provider": "databricks", "reason": str(exc)},
            ) from exc
        if not host:
            raise ProviderConfigurationError("DATABRICKS_HOST is missing.")

        column_types = [
            ("record_id", "STRING"),
            ("scene_id", "STRING"),
            ("character_key", "STRING"),
            ("record_type", "STRING"),
            ("content", "STRING"),
            ("title", "STRING"),
            ("url", "STRING"),
            ("freshness", "STRING"),
            ("importance", "INT"),
            ("visibility", "STRING"),
        ]
        select_rows: list[str] = []
        parameters: list[dict[str, Any]] = []
        for row_index, record in enumerate(records):
            selectors: list[str] = []
            for column, sql_type in column_types:
                name = f"{column}_{row_index}"
                selector = f":{name} AS {column}" if row_index == 0 else f":{name}"
                selectors.append(selector)
                value = record.get(column)
                parameters.append({
                    "name": name,
                    "value": None if value is None else str(value),
                    "type": sql_type,
                })
            select_rows.append(f"SELECT {', '.join(selectors)}")

        table = (
            f"{self.settings.databricks_catalog}.{self.settings.databricks_schema}.scene_memory_search"
        )
        columns = ", ".join(column for column, _ in column_types)
        updates = ", ".join(
            f"target.{column} = incoming.{column}"
            for column, _ in column_types
            if column != "record_id"
        )
        statement = (
            f"MERGE INTO {table} AS target USING ({' UNION ALL '.join(select_rows)}) AS incoming "
            f"ON target.record_id = incoming.record_id "
            f"WHEN MATCHED THEN UPDATE SET {updates}, target.updated_at = current_timestamp() "
            f"WHEN NOT MATCHED THEN INSERT ({columns}, updated_at) "
            f"VALUES ({', '.join(f'incoming.{column}' for column, _ in column_types)}, current_timestamp())"
        )
        payload = {
            "warehouse_id": self.settings.databricks_sql_warehouse_id,
            "catalog": self.settings.databricks_catalog,
            "schema": self.settings.databricks_schema,
            "statement": statement,
            "parameters": parameters,
            "wait_timeout": "30s",
            "on_wait_timeout": "CONTINUE",
        }
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=self.settings.databricks_timeout_seconds) as client:
            try:
                response = await client.post(
                    f"{host}/api/2.0/sql/statements",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                deadline = asyncio.get_running_loop().time() + self.settings.databricks_timeout_seconds
                while (result.get("status") or {}).get("state") in {"PENDING", "RUNNING"}:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise ExternalProviderError("Databricks memory indexing timed out.")
                    await asyncio.sleep(0.5)
                    response = await client.get(
                        f"{host}/api/2.0/sql/statements/{result['statement_id']}",
                        headers=headers,
                    )
                    response.raise_for_status()
                    result = response.json()
            except httpx.HTTPStatusError as exc:
                raise ExternalProviderError(
                    "Databricks memory indexing failed.",
                    details={"status": exc.response.status_code, "response": exc.response.text[:1200]},
                ) from exc
            except httpx.HTTPError as exc:
                raise ExternalProviderError(
                    "Databricks memory indexing could not be completed.",
                    details={"reason": str(exc)},
                ) from exc
        status = result.get("status") or {}
        if status.get("state") != "SUCCEEDED":
            raise ExternalProviderError(
                "Databricks memory indexing did not succeed.",
                details={"status": status},
            )

    async def _query(self, *, scene_id: uuid.UUID, query: str) -> list[dict[str, Any]]:
        if not self.settings.databricks_ai_search_index.strip():
            raise ProviderConfigurationError(
                "Databricks AI Search is not configured.",
                details={"missing": ["DATABRICKS_AI_SEARCH_INDEX"]},
            )
        try:
            from databricks.sdk import WorkspaceClient
        except ImportError as exc:
            raise ProviderConfigurationError(
                "The Databricks SDK is required. Install requirements.txt and restart EmotionOS."
            ) from exc

        try:
            workspace = WorkspaceClient()
            headers = dict(workspace.config.authenticate())
            host = (self.settings.databricks_host or workspace.config.host or "").rstrip("/")
            if host and "://" not in host:
                host = f"https://{host}"
        except Exception as exc:
            raise ProviderConfigurationError(
                "Databricks authentication failed while opening scene memory.",
                details={"provider": "databricks", "reason": str(exc)},
            ) from exc
        if not host:
            raise ProviderConfigurationError("DATABRICKS_HOST is missing.")

        index_name = quote(self.settings.databricks_ai_search_index.strip(), safe="")
        payload = {
            "columns": self.columns,
            "filters_json": json.dumps({"scene_id": str(scene_id)}),
            "num_results": 12,
            "query_text": query,
            "query_type": "HYBRID",
        }
        headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(timeout=self.settings.databricks_timeout_seconds) as client:
                response = await client.post(
                    f"{host}/api/2.0/vector-search/indexes/{index_name}/query",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExternalProviderError(
                "Databricks AI Search request failed.",
                details={
                    "provider": "databricks",
                    "status": exc.response.status_code,
                    "response": exc.response.text[:1200],
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalProviderError(
                "Databricks AI Search could not be reached.",
                details={"provider": "databricks", "reason": str(exc)},
            ) from exc

        data = response.json()
        column_names = [
            str(item.get("name"))
            for item in (data.get("manifest") or {}).get("columns") or []
            if isinstance(item, dict) and item.get("name")
        ]
        if not column_names:
            return []
        rows = (data.get("result") or {}).get("data_array") or []
        return [
            dict(zip(column_names, row, strict=False))
            for row in rows
            if isinstance(row, list)
        ]

    @staticmethod
    def _merge(
        primary: list[dict[str, Any]],
        secondary: list[dict[str, Any]],
        *,
        key: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [*primary, *secondary]:
            marker = str(item.get(key) or "")
            if marker and marker in seen:
                continue
            if marker:
                seen.add(marker)
            merged.append(item)
            if len(merged) >= limit:
                break
        return merged


def build_scene_retriever(settings: Settings) -> SceneRetriever:
    if settings.scene_retrieval_provider == "database":
        if not (settings.test_mode or settings.app_env.strip().lower() == "development"):
            raise RuntimeError("Database-only scene retrieval is limited to test and development")
        return DatabaseSceneRetriever()
    return DatabricksAISearchRetriever(settings)





from __future__ import annotations

import json
import re
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import ExternalProviderError, ProviderConfigurationError


class DatabricksFoundationModelClient:
    """Small, strict adapter around a Databricks Foundation Model endpoint."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.settings.databricks_configured

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2800,
        request_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        if not self.settings.databricks_serving_endpoint.strip():
            raise ProviderConfigurationError(
                "Databricks scene compilation is not configured.",
                details={"missing": ["DATABRICKS_SERVING_ENDPOINT"]},
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
                "Databricks authentication failed. Log in with the Databricks CLI or configure app OAuth.",
                details={"provider": "databricks", "reason": str(exc)},
            ) from exc

        if not host:
            raise ProviderConfigurationError(
                "DATABRICKS_HOST is missing.",
                details={"missing": ["DATABRICKS_HOST"]},
            )

        endpoint = quote(self.settings.databricks_serving_endpoint.strip(), safe="")
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": max_tokens,
            "client_request_id": request_id or str(uuid.uuid4()),
        }
        headers["Content-Type"] = "application/json"

        try:
            async with httpx.AsyncClient(timeout=self.settings.databricks_timeout_seconds) as client:
                response = await client.post(
                    f"{host}/serving-endpoints/{endpoint}/invocations",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1200]
            raise ExternalProviderError(
                "Databricks Foundation Model request failed.",
                details={"provider": "databricks", "status": exc.response.status_code, "response": body},
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalProviderError(
                "Databricks Foundation Model request could not be completed.",
                details={"provider": "databricks", "reason": str(exc)},
            ) from exc

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalProviderError(
                "Databricks returned an unexpected response.",
                details={"provider": "databricks", "response_keys": sorted(data) if isinstance(data, dict) else []},
            ) from exc

        if isinstance(content, list):
            content = "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            )
        if not isinstance(content, str):
            raise ExternalProviderError("Databricks returned no JSON text.")

        usage = data.get("usage") or {}
        return self._parse_json(content), {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ExternalProviderError("Databricks did not return a JSON object.")
            try:
                value = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ExternalProviderError(
                    "Databricks returned invalid JSON.",
                    details={"reason": str(exc)},
                ) from exc
        if not isinstance(value, dict):
            raise ExternalProviderError("Databricks must return one JSON object.")
        return value


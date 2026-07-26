from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Protocol

import httpx

from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import ExternalProviderError, ProviderConfigurationError


class SceneResearchProvider(Protocol):
    provider_name: str

    async def research(self, queries: list[str]) -> tuple[dict[str, Any], dict[str, int]]: ...


class NoResearchProvider:
    provider_name = "none"

    async def research(self, queries: list[str]) -> tuple[dict[str, Any], dict[str, int]]:
        if queries:
            raise ProviderConfigurationError(
                "This scene requires fresh research, but SCENE_RESEARCH_PROVIDER=none.",
                details={"required_searches": queries},
            )
        return {"entities": [], "sources": [], "warnings": []}, {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }


class OpenAIWebResearchProvider:
    provider_name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def research(self, queries: list[str]) -> tuple[dict[str, Any], dict[str, int]]:
        if not queries:
            return {"entities": [], "sources": [], "warnings": []}, {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        if not self.settings.openai_configured:
            raise ProviderConfigurationError(
                "Fresh scene research requires OPENAI_API_KEY.",
                details={"missing": ["OPENAI_API_KEY"]},
            )

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "stable_facts": {"type": "array", "items": {"type": "string"}},
                            "current_facts": {"type": "array", "items": {"type": "string"}},
                            "public_mannerisms": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "stable_facts", "current_facts", "public_mannerisms"],
                    },
                },
                "sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "snippet": {"type": "string"},
                            "freshness": {"type": "string", "enum": ["stable", "current"]},
                            "published_at": {"type": ["string", "null"]},
                            "supports": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["id", "title", "url", "snippet", "freshness", "published_at", "supports"],
                    },
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["entities", "sources", "warnings"],
        }
        prompt = (
            "Research the following scene preparation questions using approved public web sources. Resolve entity "
            "spelling. Prefer primary, official, and reputable sources. Separate stable facts from current facts. "
            "Every volatile claim must be supported by a source URL and date when available. Extract only high-level "
            "public speaking traits; do not copy long quotations and do not claim a synthetic voice is the real person. "
            "Return compact JSON matching the required schema.\n\nQueries:\n- "
            + "\n- ".join(queries[:8])
        )
        payload = {
            "model": self.settings.openai_research_model,
            "input": prompt,
            "tools": [{"type": "web_search"}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "scene_research_packet",
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": 2200,
            "store": False,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.settings.openai_timeout_seconds) as client:
                    response = await client.post(
                        f"{self.settings.openai_base_url.rstrip('/')}/responses",
                        headers=headers,
                        json=payload,
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                raise ExternalProviderError(
                    "OpenAI scene research failed.",
                    details={"status": exc.response.status_code, "response": exc.response.text[:1200]},
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise ExternalProviderError(
                    "OpenAI scene research could not be completed.",
                    details={"reason": str(exc)},
                ) from exc

        if response is None:
            raise ExternalProviderError("OpenAI scene research returned no response.")
        data = response.json()
        content = self._output_text(data)
        try:
            packet = json.loads(content)
        except json.JSONDecodeError:
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
            try:
                packet = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                raise ExternalProviderError(
                    "OpenAI scene research returned invalid JSON.",
                    details={"reason": str(exc)},
                ) from exc
        if not isinstance(packet, dict):
            raise ExternalProviderError("OpenAI scene research must return one JSON object.")

        usage = data.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return packet, {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
        }

    @staticmethod
    def _output_text(data: dict[str, Any]) -> str:
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        parts: list[str] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    parts.append(str(content.get("text") or ""))
        text = "".join(parts).strip()
        if not text:
            raise ExternalProviderError("OpenAI scene research returned no output text.")
        return text


def build_scene_research_provider(settings: Settings) -> SceneResearchProvider:
    if settings.scene_research_provider == "none":
        return NoResearchProvider()
    return OpenAIWebResearchProvider(settings)


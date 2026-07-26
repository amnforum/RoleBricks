from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import httpx

from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import AudioGenerationError, ValidationError


_ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac", ".mp4", ".mpeg"}


class RetryableTranscriptionError(AudioGenerationError):
    pass


class OpenAITranscriptionService:
    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory

    async def transcribe(
        self,
        *,
        filename: str,
        content_type: str,
        contents: bytes,
    ) -> str:
        if not self.settings.openai_configured:
            raise AudioGenerationError("OPENAI_API_KEY is required for voice input")
        if not contents:
            raise ValidationError("Record a non-empty voice message")
        if len(contents) > self.settings.max_audio_size_mb * 1024 * 1024:
            raise ValidationError(f"Audio exceeds the {self.settings.max_audio_size_mb} MB limit")
        if Path(filename).suffix.casefold() not in _ALLOWED_AUDIO_SUFFIXES:
            raise ValidationError("Unsupported audio format")

        timeout = httpx.Timeout(self.settings.openai_timeout_seconds)
        owns_client = self.client_factory is None
        client = self.client_factory() if self.client_factory else httpx.AsyncClient(timeout=timeout)
        try:
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{self.settings.openai_base_url.rstrip('/')}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                        files={"file": (filename, contents, content_type or "application/octet-stream")},
                        data={"model": self.settings.openai_transcription_model, "response_format": "json"},
                        timeout=timeout,
                    )
                    self._raise_for_status(response)
                    transcript = str(response.json().get("text") or "").strip()
                    if not transcript:
                        raise AudioGenerationError("OpenAI transcription returned no dialogue")
                    return transcript
                except RetryableTranscriptionError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.35 * (2**attempt))
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == 2:
                        raise AudioGenerationError(
                            f"OpenAI transcription request failed after retries: {exc}"
                        ) from exc
                    await asyncio.sleep(0.35 * (2**attempt))
        finally:
            if owns_client:
                await client.aclose()
        raise AudioGenerationError("OpenAI transcription failed")

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code == 401:
            raise AudioGenerationError("OpenAI rejected OPENAI_API_KEY")
        if response.status_code in {429, 500, 502, 503, 504}:
            raise RetryableTranscriptionError(
                f"OpenAI transcription is temporarily unavailable (HTTP {response.status_code})"
            )
        raise AudioGenerationError(f"OpenAI transcription failed with HTTP {response.status_code}")

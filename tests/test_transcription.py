from __future__ import annotations

import asyncio

import httpx
import pytest

from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import ValidationError
from emotionos.app.services.openai_transcription_service import OpenAITranscriptionService


def test_openai_transcription_uses_configured_api(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = request.read()
        assert b"gpt-4o-transcribe" in body
        assert b"turn.webm" in body
        return httpx.Response(200, json={"text": "My spoken scene turn."})

    service = OpenAITranscriptionService(
        Settings(OPENAI_API_KEY="test-key", AUDIO_DATA_DIR=str(tmp_path)),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    transcript = asyncio.run(
        service.transcribe(
            filename="turn.webm",
            content_type="audio/webm",
            contents=b"recorded-audio",
        )
    )

    assert transcript == "My spoken scene turn."


def test_transcription_rejects_unsupported_upload(tmp_path):
    service = OpenAITranscriptionService(
        Settings(OPENAI_API_KEY="test-key", AUDIO_DATA_DIR=str(tmp_path))
    )
    with pytest.raises(ValidationError, match="Unsupported audio format"):
        asyncio.run(
            service.transcribe(
                filename="turn.exe",
                content_type="application/octet-stream",
                contents=b"not-audio",
            )
        )

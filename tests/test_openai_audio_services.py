from __future__ import annotations

import io
import json
import math
import struct
import wave

import httpx
import pytest

from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import AudioGenerationError
from emotionos.app.providers.openai_provider import OpenAIVoiceProvider


def wav_bytes(duration_seconds: float = 0.25, sample_rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        frames = bytearray()
        for index in range(int(duration_seconds * sample_rate)):
            sample = int(900 * math.sin(2 * math.pi * 220 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        audio.writeframes(bytes(frames))
    return buffer.getvalue()


def test_openai_voice_provider_requires_key_without_fallback(tmp_path):
    provider = OpenAIVoiceProvider(Settings(OPENAI_API_KEY="", AUDIO_DATA_DIR=str(tmp_path)))

    assert provider.status().ready is False
    with pytest.raises(AudioGenerationError, match="OPENAI_API_KEY is required"):
        provider.generate("Hello", "cedar")


def test_openai_voice_provider_streams_wav_to_file(tmp_path):
    speech = wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        assert request.headers["authorization"] == "Bearer test-key"
        assert b'"model":"gpt-4o-mini-tts"' in request.read()
        return httpx.Response(200, content=speech, headers={"content-type": "audio/wav"})

    provider = OpenAIVoiceProvider(
        Settings(OPENAI_API_KEY="test-key", AUDIO_DATA_DIR=str(tmp_path)),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    generated = provider.generate("Teach this carefully.", "cedar", instructions="Firm and precise.")
    try:
        assert generated.engine_name == "openai-tts"
        assert generated.path.read_bytes() == speech
        assert generated.duration_seconds > 0
    finally:
        generated.path.unlink(missing_ok=True)


def test_openai_voice_provider_sends_configured_custom_voice_object(tmp_path):
    speech = wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["voice"] == {"id": "voice_consent_123"}
        return httpx.Response(200, content=speech, headers={"content-type": "audio/wav"})

    provider = OpenAIVoiceProvider(
        Settings(
            OPENAI_API_KEY="test-key",
            OPENAI_CUSTOM_VOICE_ID="voice_consent_123",
            AUDIO_DATA_DIR=str(tmp_path),
        ),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    generated = provider.generate("Keep the speaker identity.", "voice_consent_123")
    try:
        assert generated.path.read_bytes() == speech
    finally:
        generated.path.unlink(missing_ok=True)


def test_openai_voice_provider_normalizes_streaming_wav_header(tmp_path):
    speech = bytearray(wav_bytes())
    speech[4:8] = b"\xff\xff\xff\xff"
    speech[40:44] = b"\xff\xff\xff\xff"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bytes(speech), headers={"content-type": "audio/wav"})

    provider = OpenAIVoiceProvider(
        Settings(OPENAI_API_KEY="test-key", AUDIO_DATA_DIR=str(tmp_path)),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    generated = provider.generate("A short streamed sample.", "cedar")
    try:
        assert 0.2 <= generated.duration_seconds <= 0.3
        header = generated.path.read_bytes()[:44]
        assert header[4:8] != b"\xff\xff\xff\xff"
        assert header[40:44] != b"\xff\xff\xff\xff"
    finally:
        generated.path.unlink(missing_ok=True)

from __future__ import annotations

import base64
import io
import json
import math
import struct
import wave

import httpx
import pytest

from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import AudioGenerationError
from emotionos.app.domain.schemas import PerformancePlan, SpeechProfile
from emotionos.app.providers.base import VoiceGenerationContext
from emotionos.app.providers.routing_policy import VoiceRoutingPolicy, accent_delivery_instruction
from emotionos.app.providers.sarvam_provider import SarvamVoiceProvider


def wav_bytes(duration_seconds: float = 0.2, sample_rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        frames = bytearray()
        for index in range(int(duration_seconds * sample_rate)):
            sample = int(800 * math.sin(2 * math.pi * 180 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        audio.writeframes(bytes(frames))
    return buffer.getvalue()


def performance_plan() -> PerformancePlan:
    return PerformancePlan(
        primary_emotion="warmth",
        visible_emotion="confidence",
        hidden_emotion="care",
        memory_score=0.2,
        pace=1.1,
        pitch_semitones=0,
        volume_db=0,
        energy=0.65,
        pause_duration_ms=140,
        performance_note="Speak like a trusted friend.",
        explanation="Persona direction",
    )


def test_sarvam_provider_sends_bulbul_v3_profile_and_decodes_wav(tmp_path):
    speech = wav_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/text-to-speech"
        assert request.headers["api-subscription-key"] == "sarvam-test-key"
        payload = json.loads(request.read())
        assert payload["text"] == "Yeh story dil se suno."
        assert payload["target_language_code"] == "hi-IN"
        assert payload["speaker"] == "priya"
        assert payload["model"] == "bulbul:v3"
        assert payload["output_audio_codec"] == "wav"
        assert payload["pace"] == 1.065
        assert 0.7 <= payload["temperature"] <= 0.85
        return httpx.Response(200, json={"audios": [base64.b64encode(speech).decode("ascii")]})

    settings = Settings(SARVAM_API_KEY="sarvam-test-key", AUDIO_DATA_DIR=str(tmp_path))
    provider = SarvamVoiceProvider(
        settings,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    context = VoiceGenerationContext(
        voice_mode="adaptive_stock",
        speech_profile=SpeechProfile(language="hinglish-IN", accent="indian"),
        take_strength=0.65,
    )

    generated = provider.generate(
        "Yeh story dil se suno.",
        "sarvam:priya",
        performance_plan(),
        context=context,
    )
    try:
        assert generated.engine_name == "sarvam-tts"
        assert generated.engine_version == "bulbul:v3"
        assert generated.sample_rate == 24000
        assert generated.path.read_bytes() == speech
    finally:
        generated.path.unlink(missing_ok=True)


def test_sarvam_provider_requires_its_key_without_fallback(tmp_path):
    provider = SarvamVoiceProvider(Settings(SARVAM_API_KEY="", AUDIO_DATA_DIR=str(tmp_path)))
    context = VoiceGenerationContext(
        voice_mode="adaptive_stock",
        speech_profile=SpeechProfile(language="hi-IN"),
    )

    with pytest.raises(AudioGenerationError, match="SARVAM_API_KEY is required"):
        provider.generate("Namaste", "sarvam:priya", context=context)


def test_adaptive_policy_routes_native_indian_and_cross_accent_independently():
    settings = Settings(
        SARVAM_FEMININE_SPEAKER="priya",
        ADAPTIVE_OPENAI_FEMININE_VOICE="marin",
    )
    policy = VoiceRoutingPolicy(settings)
    readiness = {"sarvam": True, "openai": True, "space": True}

    native = policy.select(
        "emotionos:auto:feminine",
        VoiceGenerationContext(
            voice_mode="adaptive_stock",
            speech_profile=SpeechProfile(language="hinglish-IN", accent="indian"),
        ),
        readiness,
    )
    cross_accent = policy.select(
        "emotionos:auto:feminine",
        VoiceGenerationContext(
            voice_mode="adaptive_stock",
            speech_profile=SpeechProfile(language="hi-IN", accent="british"),
        ),
        readiness,
    )

    assert (native.provider, native.voice_id) == ("sarvam", "sarvam:priya")
    assert (cross_accent.provider, cross_accent.voice_id) == ("openai", "marin")
    assert "Cross-accent" in cross_accent.rationale


def test_cross_accent_direction_keeps_british_speaker_background():
    instruction = accent_delivery_instruction(SpeechProfile(language="hi-IN", accent="british"))

    assert "British English speaker" in instruction
    assert "Do not normalize" in instruction

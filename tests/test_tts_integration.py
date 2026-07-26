from __future__ import annotations

import os

import pytest

from emotionos.app.core.config import Settings
from emotionos.app.providers.openai_provider import OpenAIVoiceProvider


@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_INTEGRATION_TESTS", "").lower() != "true" or not os.getenv("OPENAI_API_KEY"),
    reason="Set RUN_OPENAI_INTEGRATION_TESTS=true and OPENAI_API_KEY to call the real OpenAI speech API.",
)
def test_openai_tts_provider_generates_real_wav(tmp_path):
    settings = Settings(AUDIO_DATA_DIR=str(tmp_path))
    provider = OpenAIVoiceProvider(settings)
    generated = provider.generate(
        "Please submit the assignment by Friday.",
        settings.openai_tts_voice,
        instructions="Speak as a firm, precise teacher. Do not add any words.",
    )
    try:
        assert generated.path.exists()
        assert generated.path.stat().st_size > 44
        assert generated.duration_seconds > 0
        assert generated.engine_name == "openai-tts"
    finally:
        generated.path.unlink(missing_ok=True)
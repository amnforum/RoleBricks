from __future__ import annotations

from pathlib import Path
import wave

from emotionos.app.core.config import Settings
from emotionos.app.domain.schemas import PerformancePlan, SpeechProfile
from emotionos.app.providers.base import VoiceGenerationContext
from emotionos.app.providers.huggingface_space_provider import HuggingFaceSpaceVoiceProvider


def write_silence(path: Path, frames: int, sample_rate: int = 24_000) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * frames)


class FakeSpaceClient:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.calls = []

    def predict(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return str(self.output), {"engine": "test-space"}


def test_space_provider_returns_downloaded_audio(tmp_path):
    source = tmp_path / "reference.wav"
    remote_output = tmp_path / "remote.wav"
    write_silence(source, 24_000)
    write_silence(remote_output, 24_000)

    settings = Settings(HF_SPACE_ID="madteddy/emotionos-inference")
    provider = HuggingFaceSpaceVoiceProvider(settings)
    fake = FakeSpaceClient(remote_output)
    provider._client = fake
    plan = PerformancePlan(
        primary_emotion="anger",
        visible_emotion="authority",
        hidden_emotion="hurt",
        memory_score=0.4,
        pace=0.96,
        pitch_semitones=0,
        volume_db=0,
        energy=0.75,
        pause_duration_ms=120,
        performance_note="Controlled anger",
        explanation="Persona direction",
    )
    context = VoiceGenerationContext(
        voice_mode="space_clone",
        speech_profile=SpeechProfile(language="hi-IN"),
        reference_audio_path=source,
        reference_text="Namaste",
        consent_confirmed=True,
        take_strength=0.65,
    )

    generated = provider.generate(
        "Namaste",
        "space:chatterbox:source",
        plan,
        context=context,
    )

    assert generated.path.exists()
    assert generated.path != remote_output
    assert generated.duration_seconds == 1.0
    assert generated.engine_name == "emotionos-huggingface-space"
    args, kwargs = fake.calls[0]
    assert args[1] == "hi"
    assert args[3] == "anger"
    assert kwargs["api_name"] == "/generate"
    generated.path.unlink()


def test_space_provider_requires_consent_for_reference_voice(tmp_path):
    source = tmp_path / "reference.wav"
    write_silence(source, 4_000)
    provider = HuggingFaceSpaceVoiceProvider(Settings(HF_SPACE_ID="madteddy/emotionos-inference"))
    context = VoiceGenerationContext(
        voice_mode="space_clone",
        speech_profile=SpeechProfile(language="en-IN"),
        reference_audio_path=source,
        consent_confirmed=False,
    )

    try:
        provider.generate("Hello", "space:chatterbox:source", context=context)
    except Exception as exc:
        assert "permission" in str(exc)
    else:
        raise AssertionError("Speaker matching must require consent")

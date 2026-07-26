from __future__ import annotations

import math
import struct
import tempfile
import wave
from pathlib import Path

from emotionos.app.domain.schemas import PerformancePlan
from emotionos.app.providers.base import GeneratedAudio, ProviderStatus, VoiceGenerationContext, VoiceProvider


class MockProvider(VoiceProvider):
    engine_name = "mock-tts"
    engine_version = "1.1"

    def __init__(self, sample_rate: int = 24000) -> None:
        self.sample_rate = sample_rate
        self._ready = False

    def load(self) -> ProviderStatus:
        self._ready = True
        return self.status()

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            ready=self._ready,
            provider=self.engine_name,
            engine_version=self.engine_version,
            message="Mock TTS is ready. It generates deterministic WAV files for tests.",
        )

    def generate(
        self,
        text: str,
        voice_id: str,
        performance_plan: PerformancePlan | None = None,
        *,
        instructions: str | None = None,
        context: VoiceGenerationContext | None = None,
    ) -> GeneratedAudio:
        del instructions, context
        if not self._ready:
            self.load()

        words = max(len(text.split()), 1)
        pace = performance_plan.pace if performance_plan else 1.0
        energy = performance_plan.energy if performance_plan else 0.55
        pitch = performance_plan.pitch_semitones if performance_plan else 0.0
        duration = max(0.55, min(5.0, (0.48 + words * 0.17) / pace))
        sample_count = int(self.sample_rate * duration)
        fade_samples = min(sample_count // 8, int(self.sample_rate * 0.08))
        frequency = (175 + sum(ord(char) for char in voice_id) % 120) * (2 ** (pitch / 12))
        amplitude = 0.12 + energy * 0.18
        frames = bytearray(sample_count * 2)

        for index in range(sample_count):
            time_point = index / self.sample_rate
            sample = math.sin(2 * math.pi * frequency * time_point)
            sample += 0.35 * math.sin(2 * math.pi * frequency * 1.5 * time_point)
            sample += 0.08 * math.sin(2 * math.pi * 5.2 * time_point)
            envelope = 1.0
            if fade_samples and index < fade_samples:
                envelope = index / fade_samples
            elif fade_samples and index >= sample_count - fade_samples:
                envelope = (sample_count - index - 1) / fade_samples
            pcm = int(max(-0.92, min(0.92, sample * envelope * amplitude)) * 32767)
            struct.pack_into("<h", frames, index * 2, pcm)

        path = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(self.sample_rate)
            audio.writeframes(frames)
        return GeneratedAudio(
            path=path,
            duration_seconds=duration,
            sample_rate=self.sample_rate,
            format="wav",
            engine_name=self.engine_name,
            engine_version=self.engine_version,
        )

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from emotionos.app.domain.schemas import PerformancePlan, SpeechProfile


@dataclass(frozen=True)
class GeneratedAudio:
    path: Path
    duration_seconds: float
    sample_rate: int
    format: str
    engine_name: str
    engine_version: str


@dataclass(frozen=True)
class ProviderStatus:
    ready: bool
    provider: str
    engine_version: str
    message: str


@dataclass(frozen=True)
class VoiceGenerationContext:
    voice_mode: str
    speech_profile: SpeechProfile
    reference_audio_path: Path | None = None
    reference_text: str | None = None
    consent_confirmed: bool = False
    take_strength: float = 0.65


class VoiceProvider(ABC):
    engine_name: str = "unknown"
    engine_version: str = "unknown"

    @abstractmethod
    def load(self) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def generate(
        self,
        text: str,
        voice_id: str,
        performance_plan: PerformancePlan | None = None,
        *,
        instructions: str | None = None,
        context: VoiceGenerationContext | None = None,
    ) -> GeneratedAudio:
        raise NotImplementedError

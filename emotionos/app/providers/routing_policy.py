from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import AudioGenerationError
from emotionos.app.domain.schemas import SpeechProfile
from emotionos.app.providers.base import VoiceGenerationContext


ADAPTIVE_VOICE_PREFIX = "emotionos:auto:"


@dataclass(frozen=True)
class VoiceRoute:
    provider: str
    voice_id: str
    label: str
    rationale: str

    def as_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "voice_id": self.voice_id,
            "label": self.label,
            "rationale": self.rationale,
        }


class VoiceRoutingPolicy:
    """Select one declared engine before synthesis; never fail over mid-request."""

    version = "adaptive-routing-v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def is_adaptive(voice_id: str) -> bool:
        return voice_id.startswith(ADAPTIVE_VOICE_PREFIX)

    def select(
        self,
        voice_id: str,
        context: VoiceGenerationContext,
        readiness: Mapping[str, bool],
    ) -> VoiceRoute:
        if not self.is_adaptive(voice_id):
            raise AudioGenerationError("Adaptive routing requires an EmotionOS adaptive voice")

        profile = context.speech_profile
        character = "masculine" if voice_id.endswith(":masculine") else "feminine"
        native_indian = profile.accent == "indian"
        cross_accent = profile.accent == "british" and profile.language in {"hi-IN", "hinglish-IN"}

        if native_indian:
            candidates = ("sarvam", "space", "openai")
            reason = "Native Indian language and accent are best served by an India-trained speech engine."
        elif cross_accent:
            candidates = ("openai", "space", "sarvam")
            reason = "Cross-accent Hindi needs an instruction-following voice that keeps the selected speaker background."
        else:
            candidates = ("openai", "space", "sarvam")
            reason = "The selected non-Indian accent needs instruction-led pronunciation and cadence."

        provider = next((name for name in candidates if readiness.get(name, False)), None)
        if provider is None:
            raise AudioGenerationError(
                "No configured speech engine can perform this Speech Profile. Add a Sarvam, OpenAI, or Hugging Face credential and restart EmotionOS."
            )
        return VoiceRoute(
            provider=provider,
            voice_id=self._voice_id(provider, character, profile),
            label=self._label(provider),
            rationale=reason,
        )

    def _voice_id(self, provider: str, character: str, profile: SpeechProfile) -> str:
        if provider == "sarvam":
            speaker = (
                self.settings.sarvam_masculine_speaker
                if character == "masculine"
                else self.settings.sarvam_feminine_speaker
            )
            return f"sarvam:{speaker.strip().lower()}"
        if provider == "openai":
            return (
                self.settings.adaptive_openai_masculine_voice
                if character == "masculine"
                else self.settings.adaptive_openai_feminine_voice
            )
        return "space:chatterbox:default"

    @staticmethod
    def _label(provider: str) -> str:
        return {
            "sarvam": "Sarvam Bulbul v3",
            "openai": "OpenAI expressive speech",
            "space": "EmotionOS ZeroGPU",
        }[provider]


def accent_delivery_instruction(profile: SpeechProfile) -> str:
    if profile.accent == "british" and profile.language in {"hi-IN", "hinglish-IN"}:
        return (
            "The speaker is a fluent British English speaker delivering Hindi or Hinglish. Keep clearly audible British vowel colour, "
            "rhythm, and consonant habits while remaining understandable. Do not normalize the performance into a native Indian accent."
        )
    if profile.language == "hinglish-IN" and profile.accent == "indian":
        return (
            "Use natural urban Indian Hinglish. Switch between Hindi and English inside the same phrase without resetting the voice, "
            "timing, or emotional intention."
        )
    if profile.language == "hi-IN" and profile.accent == "indian":
        return "Use idiomatic native Hindi articulation, connected phrase grouping, and everyday Indian conversational timing."
    if profile.accent == "british":
        return "Use a natural contemporary British English accent with connected, conversational phrasing."
    if profile.accent == "indian":
        return "Use a natural contemporary Indian accent with idiomatic, conversational phrasing."
    return "Use clear neutral pronunciation while preserving natural sentence-level rhythm."

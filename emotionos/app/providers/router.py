from __future__ import annotations

from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import AudioGenerationError
from emotionos.app.domain.schemas import PerformancePlan
from emotionos.app.providers.base import (
    GeneratedAudio,
    ProviderStatus,
    VoiceGenerationContext,
    VoiceProvider,
)
from emotionos.app.providers.routing_policy import VoiceRoute, VoiceRoutingPolicy


class VoiceProviderRouter(VoiceProvider):
    """Choose one declared API provider before synthesis and never fail over mid-request."""

    engine_name = "emotionos-voice-router"
    engine_version = "adaptive-v3"

    def __init__(
        self,
        *,
        openai: VoiceProvider,
        sarvam: VoiceProvider,
        space: VoiceProvider | None,
        preferred: str,
        settings: Settings,
    ) -> None:
        self.providers = {
            "openai": openai,
            "sarvam": sarvam,
            "space": space,
        }
        self.preferred = preferred
        self.policy = VoiceRoutingPolicy(settings)

    def load(self) -> ProviderStatus:
        for provider in self.providers.values():
            if provider is not None:
                provider.load()
        return self.status()

    def status(self) -> ProviderStatus:
        selected = self.status_for(self.preferred)
        messages = [
            provider.status().message
            for provider in self.providers.values()
            if provider is not None
        ]
        return ProviderStatus(
            ready=selected.ready,
            provider=self.engine_name,
            engine_version=self.engine_version,
            message=" ".join(messages),
        )

    def status_for(self, provider: str) -> ProviderStatus:
        if provider == "adaptive":
            ready = any(self._readiness().values())
            return ProviderStatus(
                ready=ready,
                provider="emotionos-adaptive",
                engine_version=self.policy.version,
                message=(
                    "Adaptive quality routing is ready."
                    if ready
                    else "No speech API is configured for adaptive routing."
                ),
            )
        selected = self.providers.get(provider)
        if selected is not None:
            return selected.status()
        return ProviderStatus(False, provider, "unavailable", f"{provider} is not configured")

    def route_for(self, voice_id: str, context: VoiceGenerationContext) -> VoiceRoute:
        if self.policy.is_adaptive(voice_id):
            return self.policy.select(voice_id, context, self._readiness())
        sarvam = self.providers["sarvam"]
        space = self.providers["space"]
        if getattr(sarvam, "supports", lambda _: False)(voice_id):
            return VoiceRoute("sarvam", voice_id, "Sarvam Bulbul v3", "Sarvam was selected explicitly.")
        if space is not None and getattr(space, "supports", lambda _: False)(voice_id):
            return VoiceRoute("space", voice_id, "EmotionOS ZeroGPU", "Hugging Face was selected explicitly.")
        return VoiceRoute("openai", voice_id, "OpenAI expressive speech", "OpenAI was selected explicitly.")

    def generate(
        self,
        text: str,
        voice_id: str,
        performance_plan: PerformancePlan | None = None,
        *,
        instructions: str | None = None,
        context: VoiceGenerationContext | None = None,
    ) -> GeneratedAudio:
        if context is None:
            raise AudioGenerationError("Voice generation requires a Speech Profile")
        route = self.route_for(voice_id, context)
        provider = self.providers.get(route.provider)
        if provider is None:
            raise AudioGenerationError(f"The declared {route.provider} route is not configured")
        status = provider.status()
        if not status.ready:
            raise AudioGenerationError(f"{status.message} No other engine was tried.")
        return provider.generate(
            text,
            route.voice_id,
            performance_plan,
            instructions=instructions,
            context=context,
        )

    def _readiness(self) -> dict[str, bool]:
        return {
            name: bool(provider and provider.status().ready)
            for name, provider in self.providers.items()
        }

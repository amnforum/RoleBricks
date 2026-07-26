from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from emotionos.app.audio.validation import audio_duration_seconds
from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import AudioGenerationError
from emotionos.app.domain.schemas import PerformancePlan
from emotionos.app.providers.base import GeneratedAudio, ProviderStatus, VoiceGenerationContext, VoiceProvider


_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class RetryableOpenAIError(Exception):
    def __init__(self, status_code: int, retry_after: float | None = None) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"retryable OpenAI status {status_code}")


class OpenAIVoiceProvider(VoiceProvider):
    engine_name = "openai-tts"

    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self.engine_version = settings.openai_tts_model

    def load(self) -> ProviderStatus:
        return self.status()

    def status(self) -> ProviderStatus:
        ready = self.settings.openai_configured
        message = (
            f"OpenAI emotion voice is configured ({self.settings.openai_tts_model})."
            if ready
            else "OPENAI_API_KEY is required in .env. No fallback voice engine is enabled."
        )
        return ProviderStatus(
            ready=ready,
            provider=self.engine_name,
            engine_version=self.engine_version,
            message=message,
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
        if not self.settings.openai_configured:
            raise AudioGenerationError(
                "OPENAI_API_KEY is required. Add it to .env and restart EmotionOS; no fallback was used."
            )
        if not text.strip():
            raise AudioGenerationError("OpenAI TTS requires non-empty dialogue text")

        output = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
        timeout = httpx.Timeout(self.settings.openai_timeout_seconds)
        owns_client = self.client_factory is None
        client = self.client_factory() if self.client_factory else httpx.Client(timeout=timeout)
        payload = {
            "model": self.settings.openai_tts_model,
            "voice": self._voice_payload(voice_id),
            "input": text,
            "instructions": instructions or self._plan_instructions(performance_plan),
            "response_format": "wav",
            "speed": self._speech_speed(performance_plan),
        }
        final_error: Exception | None = None
        try:
            for attempt in range(3):
                output.unlink(missing_ok=True)
                try:
                    url = f"{self.settings.openai_base_url.rstrip('/')}/audio/speech"
                    with client.stream(
                        "POST",
                        url,
                        headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                        json=payload,
                        timeout=timeout,
                    ) as response:
                        self._raise_for_status(response)
                        with output.open("wb") as handle:
                            for chunk in response.iter_bytes():
                                if chunk:
                                    handle.write(chunk)
                    self._normalize_streaming_wav_header(output)
                    duration = audio_duration_seconds(output)
                    if duration <= 0:
                        raise AudioGenerationError("OpenAI returned an empty WAV file")
                    return GeneratedAudio(
                        path=output,
                        duration_seconds=duration,
                        sample_rate=24000,
                        format="wav",
                        engine_name=self.engine_name,
                        engine_version=self.engine_version,
                    )
                except RetryableOpenAIError as exc:
                    final_error = exc
                    if attempt < 2:
                        time.sleep(exc.retry_after if exc.retry_after is not None else 0.5 * (2**attempt))
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    final_error = exc
                    if attempt < 2:
                        time.sleep(0.5 * (2**attempt))
            output.unlink(missing_ok=True)
            if isinstance(final_error, RetryableOpenAIError) and final_error.status_code == 429:
                raise AudioGenerationError("OpenAI rate limit or credit limit reached after retrying. No fallback was used.")
            raise AudioGenerationError(f"OpenAI TTS request failed after retrying: {final_error}")
        except AudioGenerationError:
            output.unlink(missing_ok=True)
            raise
        except httpx.HTTPError as exc:
            output.unlink(missing_ok=True)
            raise AudioGenerationError(f"OpenAI TTS request failed: {exc}") from exc
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise AudioGenerationError(f"OpenAI returned invalid speech audio: {exc}") from exc
        finally:
            if owns_client:
                client.close()

    @staticmethod
    def _normalize_streaming_wav_header(path: Path) -> None:
        file_size = path.stat().st_size
        with path.open("r+b") as handle:
            header = bytearray(handle.read(44))
            if len(header) < 44 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                return
            changed = False
            if header[4:8] == b"\xff\xff\xff\xff":
                header[4:8] = max(file_size - 8, 0).to_bytes(4, "little")
                changed = True
            if header[36:40] == b"data" and header[40:44] == b"\xff\xff\xff\xff":
                header[40:44] = max(file_size - 44, 0).to_bytes(4, "little")
                changed = True
            if changed:
                handle.seek(0)
                handle.write(header)

    @staticmethod
    def _speech_speed(plan: PerformancePlan | None) -> float:
        requested = plan.pace if plan else 1.0
        return round(max(0.88, min(1.12, 1.0 + ((requested - 1.0) * 0.7))), 3)

    def _voice_payload(self, voice_id: str) -> str | dict[str, str]:
        if self.settings.openai_custom_voice_id and voice_id == self.settings.openai_custom_voice_id:
            return {"id": voice_id}
        return voice_id

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code in _RETRYABLE_STATUS_CODES:
            retry_after: float | None = None
            try:
                retry_after = min(float(response.headers.get("retry-after", "")), 5.0)
            except (TypeError, ValueError):
                pass
            raise RetryableOpenAIError(response.status_code, retry_after)
        if response.status_code == 401:
            raise AudioGenerationError("OpenAI rejected OPENAI_API_KEY. Check the key in .env and restart EmotionOS.")
        raise AudioGenerationError(f"OpenAI TTS failed with HTTP {response.status_code}.")

    def _plan_instructions(self, plan: PerformancePlan | None) -> str:
        if plan is None:
            return (
                "Read the supplied words exactly. Use a natural, neutral narration voice. "
                "Do not add, remove, paraphrase, or explain any words."
            )
        emphasis = ", ".join(plan.emphasis_words) or "none"
        return (
            "Perform the supplied words exactly as written. Do not add, remove, paraphrase, or explain words. "
            f"Primary emotion: {plan.primary_emotion}. Visible emotion: {plan.visible_emotion}. "
            f"Hidden emotion: {plan.hidden_emotion}. Delivery: {plan.performance_note}. "
            f"Pace factor: {plan.pace}. Energy: {plan.energy}. Emphasize: {emphasis}."
        )
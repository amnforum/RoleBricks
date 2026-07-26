from __future__ import annotations

import base64
import binascii
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from emotionos.app.audio.validation import read_wav_info
from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import AudioGenerationError
from emotionos.app.domain.schemas import PerformancePlan
from emotionos.app.providers.base import GeneratedAudio, ProviderStatus, VoiceGenerationContext, VoiceProvider


_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class RetryableSarvamError(Exception):
    def __init__(self, status_code: int, retry_after: float | None = None) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"retryable Sarvam status {status_code}")


class SarvamVoiceProvider(VoiceProvider):
    engine_name = "sarvam-tts"

    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self.engine_version = settings.sarvam_tts_model

    def load(self) -> ProviderStatus:
        return self.status()

    def status(self) -> ProviderStatus:
        ready = self.settings.sarvam_configured
        message = (
            f"Sarvam {self.settings.sarvam_tts_model} is configured for native Indian speech."
            if ready
            else "Add SARVAM_API_KEY to .env to enable the native Hindi, Hinglish, and Indian English route."
        )
        return ProviderStatus(ready, self.engine_name, self.engine_version, message)

    @staticmethod
    def supports(voice_id: str) -> bool:
        return voice_id.startswith("sarvam:")

    def generate(
        self,
        text: str,
        voice_id: str,
        performance_plan: PerformancePlan | None = None,
        *,
        instructions: str | None = None,
        context: VoiceGenerationContext | None = None,
    ) -> GeneratedAudio:
        del instructions
        if not self.settings.sarvam_configured:
            raise AudioGenerationError(
                "SARVAM_API_KEY is required for this declared route. Add it to .env and restart EmotionOS; no other engine was tried."
            )
        value = " ".join(text.split())
        if not value:
            raise AudioGenerationError("Sarvam TTS requires non-empty dialogue")
        if len(value) > 2500:
            raise AudioGenerationError("Sarvam Bulbul v3 passages must be 2,500 characters or shorter")
        if not self.supports(voice_id):
            raise AudioGenerationError("The selected voice does not belong to Sarvam")
        if context is None:
            raise AudioGenerationError("Sarvam TTS requires a Speech Profile")

        speaker = voice_id.split(":", 1)[1].strip().lower()
        if not speaker:
            raise AudioGenerationError("Choose a Sarvam speaker")
        payload = {
            "text": value,
            "target_language_code": self._language_code(context),
            "speaker": speaker,
            "pace": self._pace(performance_plan),
            "speech_sample_rate": self.settings.sarvam_sample_rate,
            "model": self.settings.sarvam_tts_model,
            "output_audio_codec": "wav",
            "temperature": self._temperature(context),
        }
        dictionary = self.settings.sarvam_pronunciation_dict_id.strip()
        if dictionary:
            payload["dict_id"] = dictionary

        output = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
        timeout = httpx.Timeout(self.settings.sarvam_timeout_seconds)
        owns_client = self.client_factory is None
        client = self.client_factory() if self.client_factory else httpx.Client(timeout=timeout)
        final_error: Exception | None = None
        try:
            for attempt in range(3):
                output.unlink(missing_ok=True)
                try:
                    response = client.post(
                        f"{self.settings.sarvam_base_url.rstrip('/')}/text-to-speech",
                        headers={"api-subscription-key": self.settings.sarvam_api_key},
                        json=payload,
                        timeout=timeout,
                    )
                    self._raise_for_status(response)
                    data = response.json()
                    audios = data.get("audios") if isinstance(data, dict) else None
                    encoded = audios[0] if isinstance(audios, list) and audios else ""
                    try:
                        decoded = base64.b64decode(encoded, validate=True)
                    except (ValueError, binascii.Error) as exc:
                        raise AudioGenerationError("Sarvam returned invalid base64 audio") from exc
                    output.write_bytes(decoded)
                    info = read_wav_info(output)
                    if info.duration_seconds <= 0:
                        raise AudioGenerationError("Sarvam returned an empty WAV file")
                    return GeneratedAudio(
                        path=output,
                        duration_seconds=info.duration_seconds,
                        sample_rate=info.sample_rate,
                        format="wav",
                        engine_name=self.engine_name,
                        engine_version=self.engine_version,
                    )
                except RetryableSarvamError as exc:
                    final_error = exc
                    if attempt < 2:
                        time.sleep(exc.retry_after if exc.retry_after is not None else 0.5 * (2**attempt))
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    final_error = exc
                    if attempt < 2:
                        time.sleep(0.5 * (2**attempt))
            if isinstance(final_error, RetryableSarvamError) and final_error.status_code == 429:
                raise AudioGenerationError("Sarvam rate limit or credit limit was reached after retrying. No other engine was tried.")
            raise AudioGenerationError(f"Sarvam TTS request failed after retrying: {final_error}")
        except AudioGenerationError:
            output.unlink(missing_ok=True)
            raise
        except (httpx.HTTPError, ValueError) as exc:
            output.unlink(missing_ok=True)
            raise AudioGenerationError(f"Sarvam TTS request failed: {exc}") from exc
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise AudioGenerationError(f"Sarvam returned invalid speech audio: {exc}") from exc
        finally:
            if owns_client:
                client.close()

    @staticmethod
    def _language_code(context: VoiceGenerationContext) -> str:
        language = context.speech_profile.language
        return "hi-IN" if language in {"hi-IN", "hinglish-IN"} else "en-IN"

    @staticmethod
    def _pace(plan: PerformancePlan | None) -> float:
        requested = plan.pace if plan else 1.0
        return round(max(0.9, min(1.1, 1.0 + ((requested - 1.0) * 0.65))), 3)

    @staticmethod
    def _temperature(context: VoiceGenerationContext) -> float:
        value = 0.5 + (0.42 * context.take_strength)
        if context.speech_profile.style == "story_narrator":
            value += 0.05
        elif context.speech_profile.style == "news_reporter":
            value -= 0.08
        return round(max(0.35, min(0.95, value)), 3)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code in _RETRYABLE_STATUS_CODES:
            retry_after: float | None = None
            try:
                retry_after = min(float(response.headers.get("retry-after", "")), 5.0)
            except (TypeError, ValueError):
                pass
            raise RetryableSarvamError(response.status_code, retry_after)
        if response.status_code in {401, 403}:
            raise AudioGenerationError("Sarvam rejected SARVAM_API_KEY. Check the key in .env and restart EmotionOS.")
        message = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                message = str(body.get("error") or body.get("message") or "")
        except ValueError:
            pass
        suffix = f": {message[:180]}" if message else ""
        raise AudioGenerationError(f"Sarvam TTS failed with HTTP {response.status_code}{suffix}")

from __future__ import annotations

import importlib.util
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any


from emotionos.app.audio.validation import read_wav_info
from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import AudioGenerationError, ValidationError
from emotionos.app.domain.schemas import PerformancePlan
from emotionos.app.providers.base import GeneratedAudio, ProviderStatus, VoiceGenerationContext, VoiceProvider


class HuggingFaceSpaceVoiceProvider(VoiceProvider):
    engine_name = "emotionos-huggingface-space"
    engine_version = "chatterbox-multilingual-v3"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any = None
        self._client_lock = threading.Lock()
        self._generation_lock = threading.Lock()

    def load(self) -> ProviderStatus:
        return self.status()

    def status(self) -> ProviderStatus:
        if not self.settings.hf_space_id.strip():
            return ProviderStatus(False, self.engine_name, self.engine_version, "Set HF_SPACE_ID to your public Space.")
        if importlib.util.find_spec("gradio_client") is None:
            return ProviderStatus(False, self.engine_name, self.engine_version, "Install the core requirements again to add gradio_client.")
        return ProviderStatus(
            True,
            self.engine_name,
            self.engine_version,
            f"Hugging Face Space {self.settings.hf_space_id} is configured and wakes on demand.",
        )

    def supports(self, voice_id: str) -> bool:
        return voice_id.startswith("space:chatterbox:")

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
        if not text.strip():
            raise AudioGenerationError("The Hugging Face Space requires non-empty dialogue")
        if not self.supports(voice_id):
            raise AudioGenerationError("The selected voice does not belong to the Hugging Face Space")
        if len(" ".join(text.split())) > 300:
            raise AudioGenerationError("Hugging Face voice passages must be 300 characters or shorter")
        if context is None:
            raise AudioGenerationError("The Hugging Face Space requires a Speech Profile")

        reference = context.reference_audio_path
        matching_speaker = voice_id.endswith(":source")
        if matching_speaker and reference is None:
            raise ValidationError("Speaker matching needs uploaded reference audio")
        if matching_speaker and not context.consent_confirmed:
            raise ValidationError("Confirm that you own this voice or have the speaker's permission")

        language = "hi" if context.speech_profile.language in {"hi-IN", "hinglish-IN"} else "en"
        emotion = performance_plan.primary_emotion if performance_plan else "neutral"
        intensity = context.take_strength
        pace = performance_plan.pace if performance_plan else 1.0
        client = self._get_client()

        try:
            from gradio_client import handle_file

            reference_input = handle_file(str(reference)) if reference is not None else None
            with self._generation_lock:
                result = client.predict(
                    text,
                    language,
                    reference_input,
                    emotion,
                    intensity,
                    pace,
                    0.8,
                    0,
                    bool(reference and context.consent_confirmed),
                    api_name=self.settings.hf_space_api_name,
                )
            source = self._result_path(result)
            output = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
            shutil.copyfile(source, output)
            info = read_wav_info(output)
            return GeneratedAudio(
                path=output,
                duration_seconds=info.duration_seconds,
                sample_rate=info.sample_rate,
                format="wav",
                engine_name=self.engine_name,
                engine_version=self.engine_version,
            )
        except (AudioGenerationError, ValidationError):
            raise
        except Exception as exc:
            raise AudioGenerationError(
                f"Hugging Face Space inference failed: {exc}. Check the Space status and ZeroGPU quota."
            ) from exc

    def _get_client(self):
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is None:
                try:
                    from gradio_client import Client

                    self._client = Client(
                        self.settings.hf_space_id,
                        token=self.settings.hf_token.strip() or None,
                        verbose=False,
                    )
                except Exception as exc:
                    raise AudioGenerationError(f"Could not connect to Hugging Face Space: {exc}") from exc
        return self._client

    @staticmethod
    def _result_path(result: Any) -> Path:
        value = result[0] if isinstance(result, (list, tuple)) else result
        if isinstance(value, dict):
            value = value.get("path") or value.get("url")
        path_value = Path(str(value or ""))
        if not path_value.exists() or path_value.stat().st_size <= 44:
            raise AudioGenerationError("Hugging Face Space returned no usable audio")
        return path_value

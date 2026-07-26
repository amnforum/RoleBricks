from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path

import gradio as gr
import numpy as np
import soundfile as sf
import spaces
import torch

from chatterbox.mtl_tts import ChatterboxMultilingualTTS, SUPPORTED_LANGUAGES


MODEL_VERSION = os.getenv("CHATTERBOX_T3_MODEL", "v3")
MAX_TEXT_CHARACTERS = int(os.getenv("MAX_TEXT_CHARACTERS", "300"))
MODEL: ChatterboxMultilingualTTS | None = None


def load_model() -> ChatterboxMultilingualTTS:
    global MODEL
    if MODEL is None:
        MODEL = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model=MODEL_VERSION)
    return MODEL


try:
    load_model()
except Exception as exc:
    print(f"Model startup deferred after load error: {exc}")


def emotion_controls(emotion: str, intensity: float, pace: float) -> tuple[float, float]:
    emotion_weight = {
        "neutral": 0.38,
        "warmth": 0.48,
        "authority": 0.58,
        "joy": 0.72,
        "happy": 0.72,
        "sadness": 0.66,
        "hurt": 0.68,
        "grief": 0.78,
        "anger": 0.88,
        "fear": 0.82,
        "surprise": 0.76,
        "suspicion": 0.62,
        "forgiveness": 0.52,
        "jealousy": 0.68,
    }.get((emotion or "neutral").strip().lower(), 0.55)
    strength = max(0.0, min(float(intensity), 1.0))
    exaggeration = max(0.25, min(1.25, 0.32 + (emotion_weight * strength)))

    requested_pace = max(0.85, min(float(pace), 1.15))
    cfg_weight = 0.48 + ((requested_pace - 1.0) * 0.65) - (max(0.0, exaggeration - 0.55) * 0.18)
    return round(exaggeration, 3), round(max(0.2, min(0.75, cfg_weight)), 3)


def gpu_duration(
    text: str,
    language: str,
    reference_audio: str | None,
    emotion: str,
    intensity: float,
    pace: float,
    temperature: float,
    seed: int,
    consent_confirmed: bool,
) -> int:
    del language, reference_audio, emotion, intensity, pace, temperature, seed, consent_confirmed
    return min(120, max(35, 30 + (len(text or "") // 5)))


@spaces.GPU(duration=gpu_duration)
def generate(
    text: str,
    language: str,
    reference_audio: str | None,
    emotion: str,
    intensity: float,
    pace: float,
    temperature: float,
    seed: int,
    consent_confirmed: bool,
) -> tuple[str, dict]:
    spoken_text = " ".join((text or "").split())
    if not spoken_text:
        raise gr.Error("Add dialogue before generating audio.")
    if len(spoken_text) > MAX_TEXT_CHARACTERS:
        raise gr.Error(f"Keep each request below {MAX_TEXT_CHARACTERS} characters.")
    if language not in SUPPORTED_LANGUAGES:
        raise gr.Error(f"Unsupported language: {language}")
    if reference_audio and not consent_confirmed:
        raise gr.Error("Confirm that you own the reference voice or have the speaker's permission.")

    seed_value = int(seed or random.randint(1, 2_147_483_647))
    torch.manual_seed(seed_value)
    torch.cuda.manual_seed_all(seed_value)
    np.random.seed(seed_value % (2**32 - 1))
    random.seed(seed_value)

    exaggeration, cfg_weight = emotion_controls(emotion, intensity, pace)
    model = load_model()
    generated = model.generate(
        spoken_text,
        language_id=language,
        audio_prompt_path=reference_audio or None,
        exaggeration=exaggeration,
        cfg_weight=cfg_weight,
        temperature=max(0.2, min(float(temperature), 1.4)),
    )
    waveform = generated.squeeze().detach().float().cpu().numpy()
    output = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
    sf.write(output, waveform, model.sr, subtype="PCM_16")
    metadata = {
        "engine": "emotionos-chatterbox-space",
        "base_model": "ResembleAI/chatterbox",
        "model_version": MODEL_VERSION,
        "language": language,
        "emotion": emotion,
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "seed": seed_value,
        "speaker_matched": bool(reference_audio),
        "watermarked": True,
    }
    return str(output), metadata


with gr.Blocks(title="EmotionOS Inference") as demo:
    gr.Markdown(
        "# EmotionOS Inference\n"
        "Persona-directed, multilingual emotional speech using a consented reference voice."
    )
    with gr.Row():
        with gr.Column():
            dialogue = gr.Textbox(label="Dialogue", lines=4, max_length=MAX_TEXT_CHARACTERS)
            language = gr.Dropdown(
                choices=[("English", "en"), ("Hindi", "hi")],
                value="en",
                label="Language",
            )
            reference = gr.Audio(
                sources=["upload", "microphone"],
                type="filepath",
                label="Reference voice (optional)",
            )
            consent = gr.Checkbox(
                label="I own this voice or have the speaker's permission",
                value=False,
            )
            emotion = gr.Dropdown(
                choices=[
                    "neutral", "warmth", "authority", "joy", "sadness", "grief",
                    "anger", "fear", "surprise", "suspicion", "forgiveness",
                ],
                value="warmth",
                label="Emotion",
            )
            intensity = gr.Slider(0.1, 1.0, value=0.65, step=0.05, label="Emotion intensity")
            pace = gr.Slider(0.85, 1.15, value=1.0, step=0.01, label="Pace")
            with gr.Accordion("Generation controls", open=False):
                temperature = gr.Slider(0.2, 1.4, value=0.8, step=0.05, label="Variation")
                seed = gr.Number(value=0, precision=0, label="Seed (0 = random)")
            run = gr.Button("Generate emotional voice", variant="primary")
        with gr.Column():
            output_audio = gr.Audio(label="EmotionOS output", type="filepath")
            output_metadata = gr.JSON(label="Inference metadata")

    run.click(
        generate,
        inputs=[dialogue, language, reference, emotion, intensity, pace, temperature, seed, consent],
        outputs=[output_audio, output_metadata],
        api_name="generate",
    )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1, max_size=12).launch()

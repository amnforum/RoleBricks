from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

from emotionos.app.core.exceptions import ValidationError


@dataclass(frozen=True)
class WavInfo:
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width: int
    file_size_bytes: int


def read_wav_info(path: Path | str) -> WavInfo:
    wav_path = Path(path)
    if not wav_path.exists():
        raise ValidationError("WAV file does not exist")
    try:
        with wave.open(str(wav_path), "rb") as audio:
            frames = audio.getnframes()
            sample_rate = audio.getframerate()
            duration = frames / float(sample_rate) if sample_rate else 0.0
            return WavInfo(
                duration_seconds=duration,
                sample_rate=sample_rate,
                channels=audio.getnchannels(),
                sample_width=audio.getsampwidth(),
                file_size_bytes=wav_path.stat().st_size,
            )
    except (EOFError, wave.Error) as exc:
        raise ValidationError(f"Invalid WAV file: {exc}") from exc


def validate_wav_file(path: Path | str, *, max_size_mb: int, max_seconds: int) -> WavInfo:
    wav_path = Path(path)
    if wav_path.suffix.casefold() != ".wav":
        raise ValidationError("Only WAV files are supported")
    if not wav_path.exists():
        raise ValidationError("WAV file does not exist")
    if wav_path.stat().st_size > max_size_mb * 1024 * 1024:
        raise ValidationError(f"WAV file exceeds {max_size_mb} MB")

    with wav_path.open("rb") as handle:
        header = handle.read(12)
    if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValidationError("Uploaded file is not a valid WAV file")

    info = read_wav_info(wav_path)
    if info.duration_seconds <= 0:
        raise ValidationError("Audio file is empty")
    if info.duration_seconds > max_seconds:
        raise ValidationError(f"WAV duration exceeds {max_seconds} seconds")
    return info


def audio_duration_seconds(path: Path | str) -> float:
    return read_wav_info(path).duration_seconds

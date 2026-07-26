from __future__ import annotations

import math
import struct
import uuid
import wave
from pathlib import Path

import pytest

from emotionos.app.audio.storage import StorageManager, safe_join
from emotionos.app.audio.validation import validate_wav_file
from emotionos.app.core.exceptions import StorageError, ValidationError


def write_wav(path, duration=0.2, sample_rate=16000):
    frames = bytearray()
    for index in range(int(sample_rate * duration)):
        sample = int(0.2 * 32767 * math.sin(2 * math.pi * 220 * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(frames)


def test_wav_validation_accepts_valid_wav(tmp_path):
    path = tmp_path / "valid.wav"
    write_wav(path)
    info = validate_wav_file(path, max_size_mb=10, max_seconds=30)
    assert info.duration_seconds > 0
    assert info.sample_rate == 16000


def test_maximum_duration_validation(tmp_path):
    path = tmp_path / "long.wav"
    write_wav(path, duration=1.2)
    with pytest.raises(ValidationError):
        validate_wav_file(path, max_size_mb=10, max_seconds=1)


def test_invalid_wav_header_rejected(tmp_path):
    path = tmp_path / "bad.wav"
    path.write_bytes(b"not a wave")
    with pytest.raises(ValidationError):
        validate_wav_file(path, max_size_mb=10, max_seconds=30)


def test_path_traversal_protection(tmp_path):
    with pytest.raises(StorageError):
        safe_join(tmp_path, "..", "outside.wav")


def test_storage_manager_uses_uuid_paths(tmp_path):
    storage = StorageManager(tmp_path)
    path = storage.new_audio_path(
        project_id=uuid.uuid4(),
        character_id=uuid.uuid4(),
        scene_id=uuid.uuid4(),
        segment_id=uuid.uuid4(),
        version_type="neutral",
    )
    assert path.suffix == ".wav"
    assert tmp_path.resolve() in path.resolve().parents

class _FakeFilesApi:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.directories: list[str] = []

    def create_directory(self, directory_path: str) -> None:
        self.directories.append(directory_path)

    def upload(self, file_path: str, contents, **_kwargs) -> None:
        self.files[file_path] = contents.read()

    def download_to(self, file_path: str, destination: str, **_kwargs) -> None:
        Path(destination).write_bytes(self.files[file_path])


class _FakeWorkspaceClient:
    def __init__(self) -> None:
        self.files = _FakeFilesApi()


def test_storage_manager_persists_and_restores_volume_audio(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"wave-bytes")
    storage = StorageManager(
        tmp_path / "cache",
        volume_root="/Volumes/workspace/emotionos_worlds/scene_audio",
    )
    client = _FakeWorkspaceClient()
    storage._workspace_client = client

    stored = storage.store_audio(source, "worlds", str(uuid.uuid4()), "turns")
    cached = storage.resolve(stored)
    remote = f"/Volumes/workspace/emotionos_worlds/scene_audio/{stored}"

    assert cached.read_bytes() == b"wave-bytes"
    assert client.files.files[remote] == b"wave-bytes"

    cached.unlink()
    restored = storage.resolve(stored)
    assert restored.read_bytes() == b"wave-bytes"

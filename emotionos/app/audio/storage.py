from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from emotionos.app.core.exceptions import StorageError


def _uuid_part(value: uuid.UUID | str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise StorageError(f"Invalid {field_name}") from exc


def safe_join(root: Path | str, *parts: str) -> Path:
    base = Path(root).resolve()
    candidate = base.joinpath(*parts).resolve()
    if base != candidate and base not in candidate.parents:
        raise StorageError("Unsafe audio storage path")
    return candidate


class StorageManager:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def segment_dir(
        self,
        *,
        project_id: uuid.UUID | str,
        character_id: uuid.UUID | str,
        scene_id: uuid.UUID | str,
        segment_id: uuid.UUID | str,
        version_type: str,
    ) -> Path:
        project = _uuid_part(project_id, "project_id")
        character = _uuid_part(character_id, "character_id")
        scene = _uuid_part(scene_id, "scene_id")
        segment = _uuid_part(segment_id, "segment_id")
        clean_type = version_type.replace("-", "_")
        if clean_type not in {"source", "neutral", "personality", "living_voice", "experimental_enhancement", "chunks", "previews"}:
            raise StorageError("Invalid audio version type")
        path = safe_join(
            self.root,
            "projects",
            project,
            "characters",
            character,
            "scenes",
            scene,
            "segments",
            segment,
            clean_type,
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    def new_audio_path(
        self,
        *,
        project_id: uuid.UUID | str,
        character_id: uuid.UUID | str,
        scene_id: uuid.UUID | str,
        segment_id: uuid.UUID | str,
        version_type: str,
    ) -> Path:
        return self.segment_dir(
            project_id=project_id,
            character_id=character_id,
            scene_id=scene_id,
            segment_id=segment_id,
            version_type=version_type,
        ) / f"{uuid.uuid4()}.wav"

    def source_path(
        self,
        *,
        project_id: uuid.UUID | str,
        character_id: uuid.UUID | str,
        scene_id: uuid.UUID | str,
        segment_id: uuid.UUID | str,
    ) -> Path:
        return self.new_audio_path(
            project_id=project_id,
            character_id=character_id,
            scene_id=scene_id,
            segment_id=segment_id,
            version_type="source",
        )

    def copy_source(self, source_path: Path | str, target_path: Path | str) -> None:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source_path), str(target))

    def resolve(self, stored_path: str) -> Path:
        path = Path(stored_path)
        if not path.is_absolute():
            path = self.root / path
        resolved = path.resolve()
        if self.root != resolved and self.root not in resolved.parents:
            raise StorageError("Audio path is outside the controlled storage root")
        return resolved

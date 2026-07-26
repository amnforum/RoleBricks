from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from emotionos.app.db.base import GUID, JSONBType, TimestampTZ, utc_now
from emotionos.app.db.base import Base


class TimestampMixin:
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)
    updated_at: Mapped[object] = mapped_column(
        TimestampTZ,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)

    characters: Mapped[list["Character"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    relationships: Mapped[list["Relationship"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    memories: Mapped[list["Memory"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scenes: Mapped[list["Scene"]] = relationship(back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_projects_created_at", "created_at"),)


class Character(TimestampMixin, Base):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    personality_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    active_profile_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    project: Mapped[Project] = relationship(back_populates="characters")
    profile_versions: Mapped[list["CharacterProfileVersion"]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        order_by="CharacterProfileVersion.version_number",
    )
    relationships: Mapped[list["Relationship"]] = relationship(back_populates="character", cascade="all, delete-orphan")
    memories: Mapped[list["Memory"]] = relationship(back_populates="character", cascade="all, delete-orphan")
    dialogue_segments: Mapped[list["DialogueSegment"]] = relationship(back_populates="character")

    __table_args__ = (
        Index("ix_characters_project_id", "project_id"),
        Index("ix_characters_created_at", "created_at"),
    )


class CharacterProfileVersion(Base):
    __tablename__ = "character_profile_versions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    character_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    personality: Mapped[dict] = mapped_column(JSONBType, nullable=False)
    voice_settings: Mapped[dict] = mapped_column(JSONBType, nullable=False)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)

    character: Mapped[Character] = relationship(back_populates="profile_versions")

    __table_args__ = (
        UniqueConstraint("character_id", "version_number", name="uq_profile_version_per_character"),
        Index("ix_character_profile_versions_character_id", "character_id"),
        Index("ix_character_profile_versions_created_at", "created_at"),
    )


class Relationship(TimestampMixin, Base):
    __tablename__ = "relationships"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    character_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    related_character_name: Mapped[str] = mapped_column(String(120), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    trust: Mapped[int] = mapped_column(Integer, nullable=False)
    affection: Mapped[int] = mapped_column(Integer, nullable=False)
    tension: Mapped[int] = mapped_column(Integer, nullable=False)
    fear: Mapped[int] = mapped_column(Integer, nullable=False)
    respect: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    project: Mapped[Project] = relationship(back_populates="relationships")
    character: Mapped[Character] = relationship(back_populates="relationships")

    __table_args__ = (
        Index("ix_relationships_project_id", "project_id"),
        Index("ix_relationships_character_id", "character_id"),
        Index("ix_relationships_related_character_name", "related_character_name"),
        Index("ix_relationships_created_at", "created_at"),
    )


class Memory(TimestampMixin, Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    character_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    related_character_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    event_description: Mapped[str] = mapped_column(Text, nullable=False)
    emotion: Mapped[str] = mapped_column(String(80), nullable=False)
    impact: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution: Mapped[int] = mapped_column(Integer, nullable=False)
    decay_rate: Mapped[float] = mapped_column(Float, nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    project: Mapped[Project] = relationship(back_populates="memories")
    character: Mapped[Character] = relationship(back_populates="memories")

    __table_args__ = (
        Index("ix_memories_project_id", "project_id"),
        Index("ix_memories_character_id", "character_id"),
        Index("ix_memories_related_character_name", "related_character_name"),
        Index("ix_memories_active", "character_id", "is_active"),
        Index("ix_memories_created_at", "created_at"),
    )


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    active_manifest_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    preparation: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    confirmed_at: Mapped[object | None] = mapped_column(TimestampTZ, nullable=True)
    ready_at: Mapped[object | None] = mapped_column(TimestampTZ, nullable=True)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)
    updated_at: Mapped[object] = mapped_column(
        TimestampTZ,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="scenes")
    dialogue_segments: Mapped[list["DialogueSegment"]] = relationship(back_populates="scene", cascade="all, delete-orphan")
    manifest_versions: Mapped[list["SceneManifestVersion"]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
        order_by="SceneManifestVersion.version_number",
    )
    agents: Mapped[list["SceneAgent"]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
        order_by="SceneAgent.sort_order",
    )
    preparation_jobs: Mapped[list["ScenePreparationJob"]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
    )
    sources: Mapped[list["SceneSource"]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
    )
    turns: Mapped[list["SceneTurn"]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
        order_by="SceneTurn.created_at",
    )
    world_memories: Mapped[list["SceneMemoryRecord"]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_scenes_project_id", "project_id"),
        Index("ix_scenes_status", "status"),
        Index("ix_scenes_created_at", "created_at"),
    )


class SceneManifestVersion(Base):
    __tablename__ = "scene_manifest_versions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONBType, nullable=False)
    change_reason: Mapped[str] = mapped_column(String(240), default="Scene compiled", nullable=False)
    invalidated_components: Mapped[list] = mapped_column(JSONBType, default=list, nullable=False)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)

    scene: Mapped[Scene] = relationship(back_populates="manifest_versions")

    __table_args__ = (
        UniqueConstraint("scene_id", "version_number", name="uq_scene_manifest_version"),
        Index("ix_scene_manifest_versions_scene_id", "scene_id"),
        Index("ix_scene_manifest_versions_created_at", "created_at"),
    )


class SceneAgent(Base):
    __tablename__ = "scene_agents"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    character_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("characters.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(240), nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    profile: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    runtime_state: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    voice_profile: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)
    updated_at: Mapped[object] = mapped_column(
        TimestampTZ,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    scene: Mapped[Scene] = relationship(back_populates="agents")
    character: Mapped[Character | None] = relationship()
    memories: Mapped[list["SceneMemoryRecord"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("scene_id", "agent_key", name="uq_scene_agent_key"),
        Index("ix_scene_agents_scene_id", "scene_id"),
        Index("ix_scene_agents_character_id", "character_id"),
    )


class ScenePreparationJob(Base):
    __tablename__ = "scene_preparation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    manifest_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    stage: Mapped[str] = mapped_column(String(80), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    job_data: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)
    started_at: Mapped[object | None] = mapped_column(TimestampTZ, nullable=True)
    completed_at: Mapped[object | None] = mapped_column(TimestampTZ, nullable=True)

    scene: Mapped[Scene] = relationship(back_populates="preparation_jobs")

    __table_args__ = (
        Index("ix_scene_preparation_jobs_scene_id", "scene_id"),
        Index("ix_scene_preparation_jobs_status", "status"),
    )


class SceneSource(Base):
    __tablename__ = "scene_sources"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    agent_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="web", nullable=False)
    freshness: Mapped[str] = mapped_column(String(40), default="stable", nullable=False)
    source_data: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    retrieved_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)

    scene: Mapped[Scene] = relationship(back_populates="sources")

    __table_args__ = (
        Index("ix_scene_sources_scene_id", "scene_id"),
        Index("ix_scene_sources_agent_key", "agent_key"),
    )


class SceneTurn(Base):
    __tablename__ = "scene_turns"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    speaker_type: Mapped[str] = mapped_column(String(20), nullable=False)
    speaker_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    speaker_name: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(40), default="say", nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_data: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    citations: Mapped[list] = mapped_column(JSONBType, default=list, nullable=False)
    turn_data: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)

    scene: Mapped[Scene] = relationship(back_populates="turns")

    __table_args__ = (
        Index("ix_scene_turns_scene_id", "scene_id"),
        Index("ix_scene_turns_created_at", "created_at"),
    )


class SceneMemoryRecord(Base):
    __tablename__ = "scene_memory_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("scene_agents.id", ondelete="CASCADE"),
        nullable=True,
    )
    layer: Mapped[str] = mapped_column(String(24), nullable=False)
    visibility: Mapped[str] = mapped_column(String(24), default="private", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    source_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("scene_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    memory_data: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)
    updated_at: Mapped[object] = mapped_column(
        TimestampTZ,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    scene: Mapped[Scene] = relationship(back_populates="world_memories")
    agent: Mapped[SceneAgent | None] = relationship(back_populates="memories")

    __table_args__ = (
        Index("ix_scene_memory_records_scene_id", "scene_id"),
        Index("ix_scene_memory_records_agent_id", "agent_id"),
        Index("ix_scene_memory_records_layer", "layer"),
    )


class DialogueSegment(Base):
    __tablename__ = "dialogue_segments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    character_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    speaking_to: Mapped[str] = mapped_column(String(120), nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    hidden_feeling: Mapped[str | None] = mapped_column(String(180), nullable=True)
    input_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    source_audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_audio_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_analysis: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    voice_mode: Mapped[str] = mapped_column(String(32), default="preserve_source", nullable=False)
    creator_controls: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)

    scene: Mapped[Scene] = relationship(back_populates="dialogue_segments")
    character: Mapped[Character] = relationship(back_populates="dialogue_segments")
    performance_plans: Mapped[list["PerformancePlanModel"]] = relationship(back_populates="dialogue_segment")
    audio_versions: Mapped[list["AudioVersion"]] = relationship(back_populates="dialogue_segment")
    generation_jobs: Mapped[list["GenerationJob"]] = relationship(back_populates="dialogue_segment")

    __table_args__ = (
        Index("ix_dialogue_segments_scene_id", "scene_id"),
        Index("ix_dialogue_segments_character_id", "character_id"),
        Index("ix_dialogue_segments_created_at", "created_at"),
    )


class PerformancePlanModel(Base):
    __tablename__ = "performance_plans"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    dialogue_segment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("dialogue_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    primary_emotion: Mapped[str] = mapped_column(String(80), nullable=False)
    visible_emotion: Mapped[str] = mapped_column(String(120), nullable=False)
    hidden_emotion: Mapped[str] = mapped_column(String(120), nullable=False)
    memory_score: Mapped[float] = mapped_column(Float, nullable=False)
    relevant_memory_ids: Mapped[list] = mapped_column(JSONBType, default=list, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONBType, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)

    dialogue_segment: Mapped[DialogueSegment] = relationship(back_populates="performance_plans")
    audio_versions: Mapped[list["AudioVersion"]] = relationship(back_populates="performance_plan")

    __table_args__ = (
        Index("ix_performance_plans_dialogue_segment_id", "dialogue_segment_id"),
        Index("ix_performance_plans_created_at", "created_at"),
    )


class AudioVersion(Base):
    __tablename__ = "audio_versions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    dialogue_segment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("dialogue_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    performance_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("performance_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_type: Mapped[str] = mapped_column(String(60), nullable=False)
    audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    format: Mapped[str] = mapped_column(String(12), default="wav", nullable=False)
    engine_name: Mapped[str] = mapped_column(String(80), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_restored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)

    dialogue_segment: Mapped[DialogueSegment] = relationship(back_populates="audio_versions")
    performance_plan: Mapped[PerformancePlanModel | None] = relationship(back_populates="audio_versions")

    __table_args__ = (
        Index("ix_audio_versions_dialogue_segment_id", "dialogue_segment_id"),
        Index("ix_audio_versions_request_hash", "request_hash"),
        Index("ix_audio_versions_created_at", "created_at"),
    )


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    dialogue_segment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("dialogue_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(String(32), default="render", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    director_type: Mapped[str] = mapped_column(String(32), default="openai", nullable=False)
    selected_take: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    job_data: Mapped[dict] = mapped_column(JSONBType, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)
    started_at: Mapped[object | None] = mapped_column(TimestampTZ, nullable=True)
    completed_at: Mapped[object | None] = mapped_column(TimestampTZ, nullable=True)

    dialogue_segment: Mapped[DialogueSegment] = relationship(back_populates="generation_jobs")
    chunks: Mapped[list["GenerationAudioChunk"]] = relationship(
        back_populates="generation_job",
        cascade="all, delete-orphan",
        order_by="GenerationAudioChunk.segment_index",
    )

    __table_args__ = (
        Index("ix_generation_jobs_dialogue_segment_id", "dialogue_segment_id"),
        Index("ix_generation_jobs_status", "status"),
        Index("ix_generation_jobs_job_type", "job_type"),
        Index("ix_generation_jobs_created_at", "created_at"),
    )


class GenerationAudioChunk(Base):
    __tablename__ = "generation_audio_chunks"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    generation_job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("generation_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    created_at: Mapped[object] = mapped_column(TimestampTZ, default=utc_now, nullable=False)

    generation_job: Mapped[GenerationJob] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_generation_audio_chunks_generation_job_id", "generation_job_id"),
        Index("ix_generation_audio_chunks_status", "status"),
        Index("ix_generation_audio_chunks_created_at", "created_at"),
        Index("ix_generation_audio_chunks_segment_index", "segment_index"),
    )
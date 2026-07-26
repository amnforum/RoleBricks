"""initial EmotionOS schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

UUID = sa.String(length=36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")
JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_created_at", "projects", ["created_at"])

    op.create_table(
        "characters",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("personality_summary", sa.Text(), nullable=False),
        sa.Column("active_profile_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_characters_project_id", "characters", ["project_id"])
    op.create_index("ix_characters_created_at", "characters", ["created_at"])

    op.create_table(
        "character_profile_versions",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("character_id", UUID, sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("personality", JSONB, nullable=False),
        sa.Column("voice_settings", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("character_id", "version_number", name="uq_profile_version_per_character"),
    )
    op.create_index("ix_character_profile_versions_character_id", "character_profile_versions", ["character_id"])
    op.create_index("ix_character_profile_versions_created_at", "character_profile_versions", ["created_at"])

    op.create_table(
        "relationships",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", UUID, sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("related_character_name", sa.String(length=120), nullable=False),
        sa.Column("relationship_type", sa.String(length=80), nullable=False),
        sa.Column("trust", sa.Integer(), nullable=False),
        sa.Column("affection", sa.Integer(), nullable=False),
        sa.Column("tension", sa.Integer(), nullable=False),
        sa.Column("fear", sa.Integer(), nullable=False),
        sa.Column("respect", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_relationships_project_id", "relationships", ["project_id"])
    op.create_index("ix_relationships_character_id", "relationships", ["character_id"])
    op.create_index("ix_relationships_related_character_name", "relationships", ["related_character_name"])
    op.create_index("ix_relationships_created_at", "relationships", ["created_at"])

    op.create_table(
        "memories",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", UUID, sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("related_character_name", sa.String(length=120), nullable=True),
        sa.Column("event_description", sa.Text(), nullable=False),
        sa.Column("emotion", sa.String(length=80), nullable=False),
        sa.Column("impact", sa.Integer(), nullable=False),
        sa.Column("resolution", sa.Integer(), nullable=False),
        sa.Column("decay_rate", sa.Float(), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memories_project_id", "memories", ["project_id"])
    op.create_index("ix_memories_character_id", "memories", ["character_id"])
    op.create_index("ix_memories_related_character_name", "memories", ["related_character_name"])
    op.create_index("ix_memories_active", "memories", ["character_id", "is_active"])
    op.create_index("ix_memories_created_at", "memories", ["created_at"])

    op.create_table(
        "scenes",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scenes_project_id", "scenes", ["project_id"])
    op.create_index("ix_scenes_created_at", "scenes", ["created_at"])

    op.create_table(
        "dialogue_segments",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("scene_id", UUID, sa.ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", UUID, sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("speaking_to", sa.String(length=120), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("hidden_feeling", sa.String(length=180), nullable=True),
        sa.Column("input_mode", sa.String(length=40), nullable=False),
        sa.Column("source_audio_path", sa.Text(), nullable=True),
        sa.Column("creator_controls", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dialogue_segments_scene_id", "dialogue_segments", ["scene_id"])
    op.create_index("ix_dialogue_segments_character_id", "dialogue_segments", ["character_id"])
    op.create_index("ix_dialogue_segments_created_at", "dialogue_segments", ["created_at"])

    op.create_table(
        "performance_plans",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("dialogue_segment_id", UUID, sa.ForeignKey("dialogue_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("primary_emotion", sa.String(length=80), nullable=False),
        sa.Column("visible_emotion", sa.String(length=120), nullable=False),
        sa.Column("hidden_emotion", sa.String(length=120), nullable=False),
        sa.Column("memory_score", sa.Float(), nullable=False),
        sa.Column("relevant_memory_ids", JSONB, nullable=False),
        sa.Column("parameters", JSONB, nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_performance_plans_dialogue_segment_id", "performance_plans", ["dialogue_segment_id"])
    op.create_index("ix_performance_plans_created_at", "performance_plans", ["created_at"])

    op.create_table(
        "audio_versions",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("dialogue_segment_id", UUID, sa.ForeignKey("dialogue_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("performance_plan_id", UUID, sa.ForeignKey("performance_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_type", sa.String(length=60), nullable=False),
        sa.Column("audio_path", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("format", sa.String(length=12), nullable=False),
        sa.Column("engine_name", sa.String(length=80), nullable=False),
        sa.Column("engine_version", sa.String(length=80), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("is_restored", sa.Boolean(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audio_versions_dialogue_segment_id", "audio_versions", ["dialogue_segment_id"])
    op.create_index("ix_audio_versions_request_hash", "audio_versions", ["request_hash"])
    op.create_index("ix_audio_versions_created_at", "audio_versions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audio_versions_created_at", table_name="audio_versions")
    op.drop_index("ix_audio_versions_request_hash", table_name="audio_versions")
    op.drop_index("ix_audio_versions_dialogue_segment_id", table_name="audio_versions")
    op.drop_table("audio_versions")
    op.drop_index("ix_performance_plans_created_at", table_name="performance_plans")
    op.drop_index("ix_performance_plans_dialogue_segment_id", table_name="performance_plans")
    op.drop_table("performance_plans")
    op.drop_index("ix_dialogue_segments_created_at", table_name="dialogue_segments")
    op.drop_index("ix_dialogue_segments_character_id", table_name="dialogue_segments")
    op.drop_index("ix_dialogue_segments_scene_id", table_name="dialogue_segments")
    op.drop_table("dialogue_segments")
    op.drop_index("ix_scenes_created_at", table_name="scenes")
    op.drop_index("ix_scenes_project_id", table_name="scenes")
    op.drop_table("scenes")
    op.drop_index("ix_memories_created_at", table_name="memories")
    op.drop_index("ix_memories_active", table_name="memories")
    op.drop_index("ix_memories_related_character_name", table_name="memories")
    op.drop_index("ix_memories_character_id", table_name="memories")
    op.drop_index("ix_memories_project_id", table_name="memories")
    op.drop_table("memories")
    op.drop_index("ix_relationships_created_at", table_name="relationships")
    op.drop_index("ix_relationships_related_character_name", table_name="relationships")
    op.drop_index("ix_relationships_character_id", table_name="relationships")
    op.drop_index("ix_relationships_project_id", table_name="relationships")
    op.drop_table("relationships")
    op.drop_index("ix_character_profile_versions_created_at", table_name="character_profile_versions")
    op.drop_index("ix_character_profile_versions_character_id", table_name="character_profile_versions")
    op.drop_table("character_profile_versions")
    op.drop_index("ix_characters_created_at", table_name="characters")
    op.drop_index("ix_characters_project_id", table_name="characters")
    op.drop_table("characters")
    op.drop_index("ix_projects_created_at", table_name="projects")
    op.drop_table("projects")
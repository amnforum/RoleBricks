"""add versioned living scene workflow

Revision ID: 0004_living_scenes
Revises: 0003_persona_studio
Create Date: 2026-07-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_living_scenes"
down_revision = "0003_persona_studio"
branch_labels = None
depends_on = None

UUID = sa.String(length=36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")
JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    bind = op.get_bind()
    added_timestamp_default = (
        sa.text("'1970-01-01 00:00:00'")
        if bind.dialect.name == "sqlite"
        else sa.func.now()
    )

    op.add_column("scenes", sa.Column("raw_prompt", sa.Text(), nullable=False, server_default=""))
    op.add_column("scenes", sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"))
    op.add_column(
        "scenes",
        sa.Column("active_manifest_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "scenes",
        sa.Column("manifest", JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "scenes",
        sa.Column("preparation", JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("scenes", sa.Column("confirmed_at", TIMESTAMP, nullable=True))
    op.add_column("scenes", sa.Column("ready_at", TIMESTAMP, nullable=True))
    op.add_column(
        "scenes",
        sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=added_timestamp_default),
    )
    if bind.dialect.name == "sqlite":
        op.execute(sa.text("UPDATE scenes SET updated_at = CURRENT_TIMESTAMP"))
    op.create_index("ix_scenes_status", "scenes", ["status"])

    op.create_table(
        "scene_manifest_versions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("scene_id", UUID, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("manifest", JSON, nullable=False),
        sa.Column("change_reason", sa.String(length=240), nullable=False, server_default="Scene compiled"),
        sa.Column(
            "invalidated_components",
            JSON,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_id", "version_number", name="uq_scene_manifest_version"),
    )
    op.create_index(
        "ix_scene_manifest_versions_scene_id",
        "scene_manifest_versions",
        ["scene_id"],
    )
    op.create_index(
        "ix_scene_manifest_versions_created_at",
        "scene_manifest_versions",
        ["created_at"],
    )

    op.create_table(
        "scene_agents",
        sa.Column("id", UUID, nullable=False),
        sa.Column("scene_id", UUID, nullable=False),
        sa.Column("character_id", UUID, nullable=True),
        sa.Column("agent_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=240), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("profile", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("runtime_state", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("voice_profile", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_id", "agent_key", name="uq_scene_agent_key"),
    )
    op.create_index("ix_scene_agents_scene_id", "scene_agents", ["scene_id"])
    op.create_index("ix_scene_agents_character_id", "scene_agents", ["character_id"])

    op.create_table(
        "scene_preparation_jobs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("scene_id", UUID, nullable=False),
        sa.Column("manifest_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=80), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("job_data", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", TIMESTAMP, nullable=True),
        sa.Column("completed_at", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scene_preparation_jobs_scene_id",
        "scene_preparation_jobs",
        ["scene_id"],
    )
    op.create_index(
        "ix_scene_preparation_jobs_status",
        "scene_preparation_jobs",
        ["status"],
    )

    op.create_table(
        "scene_sources",
        sa.Column("id", UUID, nullable=False),
        sa.Column("scene_id", UUID, nullable=False),
        sa.Column("agent_key", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="web"),
        sa.Column("freshness", sa.String(length=40), nullable=False, server_default="stable"),
        sa.Column("source_data", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("retrieved_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scene_sources_scene_id", "scene_sources", ["scene_id"])
    op.create_index("ix_scene_sources_agent_key", "scene_sources", ["agent_key"])

    op.create_table(
        "scene_turns",
        sa.Column("id", UUID, nullable=False),
        sa.Column("scene_id", UUID, nullable=False),
        sa.Column("speaker_type", sa.String(length=20), nullable=False),
        sa.Column("speaker_key", sa.String(length=80), nullable=True),
        sa.Column("speaker_name", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False, server_default="say"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("audio_path", sa.Text(), nullable=True),
        sa.Column("audio_data", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("citations", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("turn_data", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scene_turns_scene_id", "scene_turns", ["scene_id"])
    op.create_index("ix_scene_turns_created_at", "scene_turns", ["created_at"])

    op.create_table(
        "scene_memory_records",
        sa.Column("id", UUID, nullable=False),
        sa.Column("scene_id", UUID, nullable=False),
        sa.Column("agent_id", UUID, nullable=True),
        sa.Column("layer", sa.String(length=24), nullable=False),
        sa.Column("visibility", sa.String(length=24), nullable=False, server_default="private"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("source_turn_id", UUID, nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("memory_data", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["scene_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_turn_id"], ["scene_turns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scene_memory_records_scene_id",
        "scene_memory_records",
        ["scene_id"],
    )
    op.create_index(
        "ix_scene_memory_records_agent_id",
        "scene_memory_records",
        ["agent_id"],
    )
    op.create_index(
        "ix_scene_memory_records_layer",
        "scene_memory_records",
        ["layer"],
    )


def downgrade() -> None:
    op.drop_index("ix_scene_memory_records_layer", table_name="scene_memory_records")
    op.drop_index("ix_scene_memory_records_agent_id", table_name="scene_memory_records")
    op.drop_index("ix_scene_memory_records_scene_id", table_name="scene_memory_records")
    op.drop_table("scene_memory_records")
    op.drop_index("ix_scene_turns_created_at", table_name="scene_turns")
    op.drop_index("ix_scene_turns_scene_id", table_name="scene_turns")
    op.drop_table("scene_turns")
    op.drop_index("ix_scene_sources_agent_key", table_name="scene_sources")
    op.drop_index("ix_scene_sources_scene_id", table_name="scene_sources")
    op.drop_table("scene_sources")
    op.drop_index("ix_scene_preparation_jobs_status", table_name="scene_preparation_jobs")
    op.drop_index("ix_scene_preparation_jobs_scene_id", table_name="scene_preparation_jobs")
    op.drop_table("scene_preparation_jobs")
    op.drop_index("ix_scene_agents_character_id", table_name="scene_agents")
    op.drop_index("ix_scene_agents_scene_id", table_name="scene_agents")
    op.drop_table("scene_agents")
    op.drop_index("ix_scene_manifest_versions_created_at", table_name="scene_manifest_versions")
    op.drop_index("ix_scene_manifest_versions_scene_id", table_name="scene_manifest_versions")
    op.drop_table("scene_manifest_versions")
    op.drop_index("ix_scenes_status", table_name="scenes")
    op.drop_column("scenes", "updated_at")
    op.drop_column("scenes", "ready_at")
    op.drop_column("scenes", "confirmed_at")
    op.drop_column("scenes", "preparation")
    op.drop_column("scenes", "manifest")
    op.drop_column("scenes", "active_manifest_version")
    op.drop_column("scenes", "status")
    op.drop_column("scenes", "raw_prompt")


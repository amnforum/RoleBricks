"""add streaming generation jobs

Revision ID: 0002_generation_jobs
Revises: 0001_initial
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_generation_jobs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

UUID = sa.String(length=36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def upgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("dialogue_segment_id", UUID, sa.ForeignKey("dialogue_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("director_type", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_generation_jobs_dialogue_segment_id", "generation_jobs", ["dialogue_segment_id"])
    op.create_index("ix_generation_jobs_status", "generation_jobs", ["status"])
    op.create_index("ix_generation_jobs_created_at", "generation_jobs", ["created_at"])

    op.create_table(
        "generation_audio_chunks",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("generation_job_id", UUID, sa.ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("audio_path", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_generation_audio_chunks_generation_job_id", "generation_audio_chunks", ["generation_job_id"])
    op.create_index("ix_generation_audio_chunks_status", "generation_audio_chunks", ["status"])
    op.create_index("ix_generation_audio_chunks_created_at", "generation_audio_chunks", ["created_at"])
    op.create_index("ix_generation_audio_chunks_segment_index", "generation_audio_chunks", ["segment_index"])


def downgrade() -> None:
    op.drop_index("ix_generation_audio_chunks_segment_index", table_name="generation_audio_chunks")
    op.drop_index("ix_generation_audio_chunks_created_at", table_name="generation_audio_chunks")
    op.drop_index("ix_generation_audio_chunks_status", table_name="generation_audio_chunks")
    op.drop_index("ix_generation_audio_chunks_generation_job_id", table_name="generation_audio_chunks")
    op.drop_table("generation_audio_chunks")
    op.drop_index("ix_generation_jobs_created_at", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_status", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_dialogue_segment_id", table_name="generation_jobs")
    op.drop_table("generation_jobs")
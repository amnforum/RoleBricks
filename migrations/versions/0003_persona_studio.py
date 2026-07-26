"""add persona studio workflow metadata

Revision ID: 0003_persona_studio
Revises: 0002_generation_jobs
Create Date: 2026-07-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_persona_studio"
down_revision = "0002_generation_jobs"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("dialogue_segments", sa.Column("source_audio_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "dialogue_segments",
        sa.Column("audio_analysis", JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "dialogue_segments",
        sa.Column("voice_mode", sa.String(length=32), nullable=False, server_default="preserve_source"),
    )

    op.add_column(
        "generation_jobs",
        sa.Column("job_type", sa.String(length=32), nullable=False, server_default="render"),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
    )
    op.add_column("generation_jobs", sa.Column("selected_take", sa.Integer(), nullable=True))
    op.add_column(
        "generation_jobs",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("job_data", JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_generation_jobs_job_type", "generation_jobs", ["job_type"])


def downgrade() -> None:
    op.drop_index("ix_generation_jobs_job_type", table_name="generation_jobs")
    op.drop_column("generation_jobs", "job_data")
    op.drop_column("generation_jobs", "cancel_requested")
    op.drop_column("generation_jobs", "selected_take")
    op.drop_column("generation_jobs", "priority")
    op.drop_column("generation_jobs", "job_type")
    op.drop_column("dialogue_segments", "voice_mode")
    op.drop_column("dialogue_segments", "audio_analysis")
    op.drop_column("dialogue_segments", "source_audio_hash")
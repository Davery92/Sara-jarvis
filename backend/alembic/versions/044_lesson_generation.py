"""Add job_type column to learning_guide_job for lesson generation

Revision ID: 044_lesson_generation
Revises: 043_chapter_aware_chunks
Create Date: 2026-02-16

Adds:
- learning_guide_job.job_type — distinguishes 'guide' jobs from 'lesson' jobs
"""
from alembic import op


revision = "044_lesson_generation"
down_revision = "043_chapter_aware_chunks"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE learning_guide_job ADD COLUMN IF NOT EXISTS job_type VARCHAR(50) DEFAULT 'guide';
        """
    )


def downgrade():
    op.execute(
        """
        ALTER TABLE learning_guide_job DROP COLUMN IF EXISTS job_type;
        """
    )

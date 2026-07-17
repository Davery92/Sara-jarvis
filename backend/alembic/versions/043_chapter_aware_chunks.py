"""Add chapter-aware chunking columns

Revision ID: 043_chapter_aware_chunks
Revises: 042_candidate_skills
Create Date: 2026-02-15

Adds:
- source_chunk.chapter_ref — chapter identifier for SQL-filtered retrieval
- source_chunk.page_start — starting page number for the chunk
- topic_source.toc — JSONB table of contents extracted from PDF
"""
from alembic import op


revision = "043_chapter_aware_chunks"
down_revision = "042_candidate_skills"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE source_chunk ADD COLUMN IF NOT EXISTS chapter_ref VARCHAR(500);
        ALTER TABLE source_chunk ADD COLUMN IF NOT EXISTS page_start INTEGER;
        CREATE INDEX IF NOT EXISTS ix_source_chunk_chapter ON source_chunk (chapter_ref);

        ALTER TABLE topic_source ADD COLUMN IF NOT EXISTS toc JSONB;
        """
    )


def downgrade():
    op.execute(
        """
        DROP INDEX IF EXISTS ix_source_chunk_chapter;
        ALTER TABLE source_chunk DROP COLUMN IF EXISTS chapter_ref;
        ALTER TABLE source_chunk DROP COLUMN IF EXISTS page_start;
        ALTER TABLE topic_source DROP COLUMN IF EXISTS toc;
        """
    )

"""Create intelligence_item table for proactive tech intelligence monitor

Revision ID: 045_intelligence_items
Revises: 044_lesson_generation
Create Date: 2026-02-20

Adds:
- intelligence_item table with indexes on source_category, discovered_at,
  novelty_score, relevance_score, dismissed
"""
from alembic import op


revision = "045_intelligence_items"
down_revision = "044_lesson_generation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS intelligence_item (
            id VARCHAR PRIMARY KEY,
            source VARCHAR NOT NULL,
            source_category VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            summary TEXT,
            url VARCHAR,
            full_content TEXT,
            novelty_score FLOAT DEFAULT 0.5,
            relevance_score FLOAT DEFAULT 0.5,
            discovered_at TIMESTAMP DEFAULT NOW(),
            included_in_digest_at TIMESTAMP,
            notified_at TIMESTAMP,
            dismissed BOOLEAN DEFAULT FALSE,
            digest_text TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS ix_intelligence_item_source_category
            ON intelligence_item (source_category);
        CREATE INDEX IF NOT EXISTS ix_intelligence_item_discovered_at
            ON intelligence_item (discovered_at);
        CREATE INDEX IF NOT EXISTS ix_intelligence_item_novelty_score
            ON intelligence_item (novelty_score);
        CREATE INDEX IF NOT EXISTS ix_intelligence_item_relevance_score
            ON intelligence_item (relevance_score);
        CREATE INDEX IF NOT EXISTS ix_intelligence_item_dismissed
            ON intelligence_item (dismissed);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS intelligence_item;")

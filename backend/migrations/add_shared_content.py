"""
Migration: Add shared_content table for Content Inbox feature.
Allows David to share URLs, Reddit posts, PDFs, documents, and text to Sara.
"""
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def run_migration(db_session):
    """Create shared_content table and indexes."""
    logger.info("Running migration: add_shared_content")

    db_session.execute(text("""
        CREATE TABLE IF NOT EXISTS shared_content (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,

            content_type VARCHAR(30) NOT NULL,
            original_url TEXT,
            title VARCHAR(500),
            description TEXT,
            thumbnail_url TEXT,

            extracted_text TEXT,
            extraction_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            extraction_error TEXT,
            word_count INTEGER,

            storage_key VARCHAR(500),
            original_filename VARCHAR(500),
            mime_type VARCHAR(100),
            file_size INTEGER,

            meta JSONB DEFAULT '{}',

            status VARCHAR(20) NOT NULL DEFAULT 'unread',
            read_at TIMESTAMPTZ,
            decided_at TIMESTAMPTZ,

            discussed BOOLEAN DEFAULT FALSE,
            consolidated BOOLEAN DEFAULT FALSE,
            consolidated_at TIMESTAMPTZ,
            episode_id VARCHAR,

            embedding vector(1024),

            shared_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """))

    db_session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_shared_content_user_status
        ON shared_content(user_id, status);
    """))

    db_session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_shared_content_user_consolidated
        ON shared_content(user_id, consolidated) WHERE status = 'kept';
    """))

    db_session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_shared_content_shared_at
        ON shared_content(shared_at DESC);
    """))

    db_session.commit()
    logger.info("Migration complete: shared_content table created")


if __name__ == "__main__":
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        run_migration(db)
    finally:
        db.close()

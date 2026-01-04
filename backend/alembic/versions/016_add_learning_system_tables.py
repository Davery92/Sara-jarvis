"""Add learning system tables for Sara Learning Mode

Revision ID: 016_learning_system
Revises: 015_enhance_event_outbox
Create Date: 2025-12-04

This migration adds:
1. learning_topic - Hierarchical learning topics
2. topic_source - Web pages, PDFs, and documents for learning
3. source_chunk - Semantic chunks with embeddings for RAG
4. learning_session - Time tracking for study sessions
5. learning_progress - Spaced repetition state (SM-2)
6. topic_scratchpad - Per-topic notes visible to Sara
7. research_report - Generated research reports
8. research_job - Background job tracking for deep research
9. learning_artifact - Canvas diagrams (React Flow)

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '016_learning_system'
down_revision = '015_enhance_event_outbox'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Learning Topics - hierarchical knowledge organization
    op.execute("""
        CREATE TABLE IF NOT EXISTS learning_topic (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            parent_id VARCHAR(36) REFERENCES learning_topic(id) ON DELETE SET NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            status VARCHAR(50) DEFAULT 'active',
            mastery_level DOUBLE PRECISION DEFAULT 0.0,
            priority INTEGER DEFAULT 5,
            meta JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_topic_user ON learning_topic (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_topic_parent ON learning_topic (parent_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_topic_status ON learning_topic (status);")

    # 2. Topic Sources - web pages, PDFs, documents
    op.execute("""
        CREATE TABLE IF NOT EXISTS topic_source (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            topic_id VARCHAR(36) NOT NULL REFERENCES learning_topic(id) ON DELETE CASCADE,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            source_type VARCHAR(50) NOT NULL,
            url TEXT,
            title VARCHAR(500),
            content_text TEXT,
            quality_score DOUBLE PRECISION DEFAULT 0.5,
            origin_reputation DOUBLE PRECISION DEFAULT 0.5,
            fetch_status VARCHAR(50) DEFAULT 'pending',
            meta JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_topic_source_topic ON topic_source (topic_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_topic_source_user ON topic_source (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_topic_source_type ON topic_source (source_type);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_topic_source_status ON topic_source (fetch_status);")

    # 3. Source Chunks - semantic chunks with embeddings
    op.execute("""
        CREATE TABLE IF NOT EXISTS source_chunk (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            source_id VARCHAR(36) NOT NULL REFERENCES topic_source(id) ON DELETE CASCADE,
            chunk_idx INTEGER NOT NULL,
            text TEXT NOT NULL,
            breadcrumb VARCHAR(500),
            embedding vector(1024) NOT NULL,
            concept_tags JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_source_chunk_source ON source_chunk (source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_source_chunk_embedding ON source_chunk USING hnsw (embedding vector_l2_ops);")

    # 4. Learning Sessions - time tracking
    op.execute("""
        CREATE TABLE IF NOT EXISTS learning_session (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            topic_id VARCHAR(36) REFERENCES learning_topic(id) ON DELETE SET NULL,
            started_at TIMESTAMPTZ DEFAULT NOW(),
            ended_at TIMESTAMPTZ,
            duration_minutes INTEGER,
            session_type VARCHAR(50),
            notes TEXT,
            meta JSONB DEFAULT '{}'::jsonb
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_session_user ON learning_session (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_session_topic ON learning_session (topic_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_session_started ON learning_session (started_at);")

    # 5. Learning Progress - spaced repetition (SM-2)
    op.execute("""
        CREATE TABLE IF NOT EXISTS learning_progress (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            topic_id VARCHAR(36) REFERENCES learning_topic(id) ON DELETE CASCADE,
            source_id VARCHAR(36) REFERENCES topic_source(id) ON DELETE CASCADE,
            concept VARCHAR(500),
            ease_factor DOUBLE PRECISION DEFAULT 2.5,
            interval_days INTEGER DEFAULT 1,
            repetitions INTEGER DEFAULT 0,
            next_review_at TIMESTAMPTZ DEFAULT NOW(),
            last_reviewed_at TIMESTAMPTZ,
            quality_history JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_progress_user ON learning_progress (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_progress_topic ON learning_progress (topic_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_progress_next_review ON learning_progress (next_review_at);")

    # 6. Topic Scratchpad - per-topic notes visible to Sara
    op.execute("""
        CREATE TABLE IF NOT EXISTS topic_scratchpad (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            topic_id VARCHAR(36) NOT NULL REFERENCES learning_topic(id) ON DELETE CASCADE,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            content TEXT NOT NULL DEFAULT '',
            version INTEGER DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(topic_id, user_id)
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_topic_scratchpad_topic ON topic_scratchpad (topic_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_topic_scratchpad_user ON topic_scratchpad (user_id);")

    # 7. Research Reports - generated synthesis reports
    op.execute("""
        CREATE TABLE IF NOT EXISTS research_report (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            topic_id VARCHAR(36) REFERENCES learning_topic(id) ON DELETE SET NULL,
            question TEXT NOT NULL,
            summary TEXT,
            full_content TEXT,
            confidence DOUBLE PRECISION,
            novelty_score DOUBLE PRECISION,
            sources_used JSONB DEFAULT '[]'::jsonb,
            report_type VARCHAR(50) DEFAULT 'quick',
            status VARCHAR(50) DEFAULT 'pending',
            store_in_knowledge BOOLEAN DEFAULT false,
            meta JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_research_report_user ON research_report (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_research_report_topic ON research_report (topic_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_research_report_status ON research_report (status);")

    # 8. Research Jobs - background job tracking
    op.execute("""
        CREATE TABLE IF NOT EXISTS research_job (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            report_id VARCHAR(36) REFERENCES research_report(id) ON DELETE CASCADE,
            status VARCHAR(50) DEFAULT 'queued',
            progress INTEGER DEFAULT 0,
            current_step TEXT,
            search_queries JSONB DEFAULT '[]'::jsonb,
            sources_found INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_research_job_user ON research_job (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_research_job_report ON research_job (report_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_research_job_status ON research_job (status);")

    # 9. Learning Artifacts - canvas diagrams (React Flow)
    op.execute("""
        CREATE TABLE IF NOT EXISTS learning_artifact (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            topic_id VARCHAR(36) REFERENCES learning_topic(id) ON DELETE SET NULL,
            artifact_type VARCHAR(50) NOT NULL,
            title VARCHAR(255),
            content JSONB NOT NULL DEFAULT '{}'::jsonb,
            version INTEGER DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_artifact_user ON learning_artifact (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_artifact_topic ON learning_artifact (topic_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_artifact_type ON learning_artifact (artifact_type);")


def downgrade():
    # Drop indexes first
    op.execute("DROP INDEX IF EXISTS ix_learning_artifact_type;")
    op.execute("DROP INDEX IF EXISTS ix_learning_artifact_topic;")
    op.execute("DROP INDEX IF EXISTS ix_learning_artifact_user;")
    op.execute("DROP INDEX IF EXISTS ix_research_job_status;")
    op.execute("DROP INDEX IF EXISTS ix_research_job_report;")
    op.execute("DROP INDEX IF EXISTS ix_research_job_user;")
    op.execute("DROP INDEX IF EXISTS ix_research_report_status;")
    op.execute("DROP INDEX IF EXISTS ix_research_report_topic;")
    op.execute("DROP INDEX IF EXISTS ix_research_report_user;")
    op.execute("DROP INDEX IF EXISTS ix_topic_scratchpad_user;")
    op.execute("DROP INDEX IF EXISTS ix_topic_scratchpad_topic;")
    op.execute("DROP INDEX IF EXISTS ix_learning_progress_next_review;")
    op.execute("DROP INDEX IF EXISTS ix_learning_progress_topic;")
    op.execute("DROP INDEX IF EXISTS ix_learning_progress_user;")
    op.execute("DROP INDEX IF EXISTS ix_learning_session_started;")
    op.execute("DROP INDEX IF EXISTS ix_learning_session_topic;")
    op.execute("DROP INDEX IF EXISTS ix_learning_session_user;")
    op.execute("DROP INDEX IF EXISTS ix_source_chunk_embedding;")
    op.execute("DROP INDEX IF EXISTS ix_source_chunk_source;")
    op.execute("DROP INDEX IF EXISTS ix_topic_source_status;")
    op.execute("DROP INDEX IF EXISTS ix_topic_source_type;")
    op.execute("DROP INDEX IF EXISTS ix_topic_source_user;")
    op.execute("DROP INDEX IF EXISTS ix_topic_source_topic;")
    op.execute("DROP INDEX IF EXISTS ix_learning_topic_status;")
    op.execute("DROP INDEX IF EXISTS ix_learning_topic_parent;")
    op.execute("DROP INDEX IF EXISTS ix_learning_topic_user;")

    # Drop tables in reverse order (respecting foreign keys)
    op.execute("DROP TABLE IF EXISTS learning_artifact;")
    op.execute("DROP TABLE IF EXISTS research_job;")
    op.execute("DROP TABLE IF EXISTS research_report;")
    op.execute("DROP TABLE IF EXISTS topic_scratchpad;")
    op.execute("DROP TABLE IF EXISTS learning_progress;")
    op.execute("DROP TABLE IF EXISTS learning_session;")
    op.execute("DROP TABLE IF EXISTS source_chunk;")
    op.execute("DROP TABLE IF EXISTS topic_source;")
    op.execute("DROP TABLE IF EXISTS learning_topic;")

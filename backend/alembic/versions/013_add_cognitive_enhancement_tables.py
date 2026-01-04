"""Add cognitive enhancement tables for Sara's self-memory, hypotheses, and reasoning

Revision ID: 013_cognitive_enhancement
Revises: 012_insight_embedding
Create Date: 2025-11-26

This migration adds:
1. sara_reflections - Sara's self-knowledge and learning from interactions
2. relationship_state - Tracking the Sara-David relationship evolution
3. hypotheses - Sara's explicit beliefs/theories about David
4. reasoning_traces - Captured thinking from gpt-oss
5. predictions - Calibration tracking for uncertainty

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False

# revision identifiers, used by Alembic.
revision = '013_cognitive_enhancement'
down_revision = '012_insight_embedding'
branch_labels = None
depends_on = None


def upgrade():
    # Ensure pgvector extension exists
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 1. Sara's self-reflections table
    op.execute("""
        CREATE TABLE IF NOT EXISTS sara_reflection (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            reflection_type VARCHAR(50) NOT NULL,
            domain VARCHAR(100),
            content TEXT NOT NULL,
            source_episodes JSONB DEFAULT '[]'::jsonb,
            confidence DOUBLE PRECISION DEFAULT 0.5,
            times_applied INTEGER DEFAULT 0,
            effectiveness_score DOUBLE PRECISION,
            superseded_by VARCHAR(36) REFERENCES sara_reflection(id),
            is_active BOOLEAN DEFAULT true,
            embedding VECTOR(1024),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # Indexes for sara_reflection
    op.execute("CREATE INDEX IF NOT EXISTS ix_sara_reflection_type ON sara_reflection (reflection_type);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sara_reflection_domain ON sara_reflection (domain);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sara_reflection_active ON sara_reflection (is_active);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sara_reflection_confidence ON sara_reflection (confidence);")

    # HNSW index for embedding similarity search
    try:
        op.execute("CREATE INDEX IF NOT EXISTS ix_sara_reflection_embedding ON sara_reflection USING hnsw (embedding vector_l2_ops);")
    except Exception:
        try:
            op.execute("CREATE INDEX IF NOT EXISTS ix_sara_reflection_embedding ON sara_reflection USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);")
        except Exception:
            pass

    # 2. Relationship state table (single record for tracking Sara-David relationship)
    op.execute("""
        CREATE TABLE IF NOT EXISTS relationship_state (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            phase VARCHAR(50) DEFAULT 'early',
            total_conversations INTEGER DEFAULT 0,
            total_episodes INTEGER DEFAULT 0,
            first_interaction TIMESTAMPTZ,
            topics_discussed JSONB DEFAULT '{}'::jsonb,
            shared_references JSONB DEFAULT '[]'::jsonb,
            trust_signals JSONB DEFAULT '[]'::jsonb,
            tension_events JSONB DEFAULT '[]'::jsonb,
            communication_preferences JSONB DEFAULT '{}'::jsonb,
            last_updated TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # 3. Hypotheses table - Sara's beliefs about David
    op.execute("""
        CREATE TABLE IF NOT EXISTS hypothesis (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            statement TEXT NOT NULL,
            domain VARCHAR(100) NOT NULL,
            confidence DOUBLE PRECISION DEFAULT 0.3,
            evidence_for JSONB DEFAULT '[]'::jsonb,
            evidence_against JSONB DEFAULT '[]'::jsonb,
            status VARCHAR(50) DEFAULT 'active',
            superseded_by VARCHAR(36) REFERENCES hypothesis(id),
            times_useful INTEGER DEFAULT 0,
            embedding VECTOR(1024),
            first_formed TIMESTAMPTZ DEFAULT NOW(),
            last_updated TIMESTAMPTZ DEFAULT NOW(),
            last_evidence_at TIMESTAMPTZ
        );
    """)

    # Indexes for hypothesis
    op.execute("CREATE INDEX IF NOT EXISTS ix_hypothesis_domain ON hypothesis (domain);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hypothesis_status ON hypothesis (status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hypothesis_confidence ON hypothesis (confidence);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hypothesis_last_evidence ON hypothesis (last_evidence_at);")

    # HNSW index for embedding similarity search
    try:
        op.execute("CREATE INDEX IF NOT EXISTS ix_hypothesis_embedding ON hypothesis USING hnsw (embedding vector_l2_ops);")
    except Exception:
        try:
            op.execute("CREATE INDEX IF NOT EXISTS ix_hypothesis_embedding ON hypothesis USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);")
        except Exception:
            pass

    # 4. Reasoning traces table - captured thinking from gpt-oss
    op.execute("""
        CREATE TABLE IF NOT EXISTS reasoning_trace (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            episode_id VARCHAR(36),
            conversation_id VARCHAR(36),
            thinking_content TEXT NOT NULL,
            reasoning_effort VARCHAR(20),
            tool_calls_made JSONB DEFAULT '[]'::jsonb,
            final_answer_summary TEXT,
            token_count INTEGER,
            duration_ms INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # Indexes for reasoning_trace
    op.execute("CREATE INDEX IF NOT EXISTS ix_reasoning_trace_episode ON reasoning_trace (episode_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reasoning_trace_conversation ON reasoning_trace (conversation_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reasoning_trace_created ON reasoning_trace (created_at);")

    # 5. Predictions table - for calibration tracking
    op.execute("""
        CREATE TABLE IF NOT EXISTS prediction (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            statement TEXT NOT NULL,
            domain VARCHAR(100),
            confidence DOUBLE PRECISION NOT NULL,
            source_episode_id VARCHAR(36),
            outcome VARCHAR(50),
            resolved_at TIMESTAMPTZ,
            resolution_notes TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # Indexes for prediction
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_outcome ON prediction (outcome);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_domain ON prediction (domain);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_confidence ON prediction (confidence);")


def downgrade():
    # Drop indexes first
    op.execute("DROP INDEX IF EXISTS ix_prediction_confidence;")
    op.execute("DROP INDEX IF EXISTS ix_prediction_domain;")
    op.execute("DROP INDEX IF EXISTS ix_prediction_outcome;")
    op.execute("DROP INDEX IF EXISTS ix_reasoning_trace_created;")
    op.execute("DROP INDEX IF EXISTS ix_reasoning_trace_conversation;")
    op.execute("DROP INDEX IF EXISTS ix_reasoning_trace_episode;")
    op.execute("DROP INDEX IF EXISTS ix_hypothesis_embedding;")
    op.execute("DROP INDEX IF EXISTS ix_hypothesis_last_evidence;")
    op.execute("DROP INDEX IF EXISTS ix_hypothesis_confidence;")
    op.execute("DROP INDEX IF EXISTS ix_hypothesis_status;")
    op.execute("DROP INDEX IF EXISTS ix_hypothesis_domain;")
    op.execute("DROP INDEX IF EXISTS ix_sara_reflection_embedding;")
    op.execute("DROP INDEX IF EXISTS ix_sara_reflection_confidence;")
    op.execute("DROP INDEX IF EXISTS ix_sara_reflection_active;")
    op.execute("DROP INDEX IF EXISTS ix_sara_reflection_domain;")
    op.execute("DROP INDEX IF EXISTS ix_sara_reflection_type;")

    # Drop tables
    op.execute("DROP TABLE IF EXISTS prediction;")
    op.execute("DROP TABLE IF EXISTS reasoning_trace;")
    op.execute("DROP TABLE IF EXISTS hypothesis;")
    op.execute("DROP TABLE IF EXISTS relationship_state;")
    op.execute("DROP TABLE IF EXISTS sara_reflection;")

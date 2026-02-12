"""
Migration: Add cognitive learning tables for personalized learning system
Creates: tangent_queue, known_domain, anchor_point
Alters: source_chunk (analogy_version), learning_progress (review_mode)
Single idempotent migration for all cognitive learning batches.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text


def run_migration():
    """Add cognitive learning tables and columns"""
    database_url = os.getenv("DATABASE_URL", "postgresql://sara:sara123@10.185.1.180:5432/sara_hub")
    engine = create_engine(database_url)

    with engine.connect() as conn:
        # =========================================================================
        # Batch 2: tangent_queue table
        # =========================================================================
        print("Creating tangent_queue table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tangent_queue (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                parent_topic_id VARCHAR NOT NULL REFERENCES learning_topic(id) ON DELETE CASCADE,
                tangent_description TEXT NOT NULL,
                source_context TEXT,
                priority INTEGER DEFAULT 3,
                status VARCHAR(50) DEFAULT 'queued',
                promoted_topic_id VARCHAR REFERENCES learning_topic(id) ON DELETE SET NULL,
                is_prerequisite BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        # Index for efficient querying
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tangent_queue_user_topic_status
            ON tangent_queue(user_id, parent_topic_id, status)
        """))
        print("  tangent_queue: OK")

        # =========================================================================
        # Batch 3: known_domain table
        # =========================================================================
        print("Creating known_domain table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS known_domain (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                domain_name VARCHAR(255) NOT NULL,
                description TEXT,
                proficiency VARCHAR(50) DEFAULT 'intermediate',
                key_concepts JSONB DEFAULT '[]'::jsonb,
                last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                CONSTRAINT uq_known_domain_user_name UNIQUE (user_id, domain_name)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_known_domain_user
            ON known_domain(user_id)
        """))
        print("  known_domain: OK")

        # =========================================================================
        # Batch 4: anchor_point table
        # =========================================================================
        print("Creating anchor_point table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS anchor_point (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                topic_id VARCHAR NOT NULL REFERENCES learning_topic(id) ON DELETE CASCADE,
                anchor_concept VARCHAR(500) NOT NULL,
                anchor_domain VARCHAR(255) NOT NULL,
                bridge_description TEXT,
                confidence FLOAT DEFAULT 0.5,
                validated BOOLEAN DEFAULT FALSE,
                rejected BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_anchor_point_topic_validated
            ON anchor_point(topic_id, validated)
        """))
        print("  anchor_point: OK")

        # =========================================================================
        # Batch 5: source_chunk.analogy_version column
        # =========================================================================
        print("Adding analogy_version to source_chunk...")
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'source_chunk' AND column_name = 'analogy_version'
        """))
        if not result.fetchone():
            conn.execute(text("""
                ALTER TABLE source_chunk
                ADD COLUMN analogy_version JSONB
            """))
            print("  analogy_version column: added")
        else:
            print("  analogy_version column: already exists")

        # =========================================================================
        # Batch 6: learning_progress review mode columns
        # =========================================================================
        print("Adding review_mode columns to learning_progress...")
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'learning_progress' AND column_name = 'review_mode'
        """))
        if not result.fetchone():
            conn.execute(text("""
                ALTER TABLE learning_progress
                ADD COLUMN review_mode VARCHAR(50)
            """))
            print("  review_mode column: added")
        else:
            print("  review_mode column: already exists")

        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'learning_progress' AND column_name = 'review_mode_history'
        """))
        if not result.fetchone():
            conn.execute(text("""
                ALTER TABLE learning_progress
                ADD COLUMN review_mode_history JSONB DEFAULT '[]'::jsonb
            """))
            print("  review_mode_history column: added")
        else:
            print("  review_mode_history column: already exists")

        conn.commit()
        print("\nCognitive learning migration completed successfully!")


if __name__ == "__main__":
    run_migration()

"""Add learning blueprints and topic linkage

Revision ID: 040_learning_blueprints
Revises: 039_shadow_session
Create Date: 2026-02-13

Adds:
- learning_blueprint table for imported study plans
- blueprint_id column on learning_topic for traceable materialization
"""
from alembic import op


revision = '040_learning_blueprints'
down_revision = '039_shadow_session'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS learning_blueprint (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            subtitle VARCHAR(255),
            description TEXT,
            source_format VARCHAR(50) DEFAULT 'text',
            pace_mode VARCHAR(50) DEFAULT 'self_directed',
            status VARCHAR(50) DEFAULT 'parsed',
            import_confidence DOUBLE PRECISION DEFAULT 0.5,
            raw_text TEXT NOT NULL,
            parsed_json JSONB DEFAULT '{}'::jsonb,
            materialized_at TIMESTAMPTZ,
            meta JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_blueprint_user ON learning_blueprint (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_blueprint_status ON learning_blueprint (status);")

    op.execute("ALTER TABLE learning_topic ADD COLUMN IF NOT EXISTS blueprint_id VARCHAR(36);")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_learning_topic_blueprint'
                  AND table_name = 'learning_topic'
            ) THEN
                ALTER TABLE learning_topic
                ADD CONSTRAINT fk_learning_topic_blueprint
                FOREIGN KEY (blueprint_id)
                REFERENCES learning_blueprint(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_topic_blueprint ON learning_topic (blueprint_id);")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_learning_topic_blueprint;")
    op.execute("ALTER TABLE learning_topic DROP CONSTRAINT IF EXISTS fk_learning_topic_blueprint;")
    op.execute("ALTER TABLE learning_topic DROP COLUMN IF EXISTS blueprint_id;")

    op.execute("DROP INDEX IF EXISTS ix_learning_blueprint_status;")
    op.execute("DROP INDEX IF EXISTS ix_learning_blueprint_user;")
    op.execute("DROP TABLE IF EXISTS learning_blueprint;")

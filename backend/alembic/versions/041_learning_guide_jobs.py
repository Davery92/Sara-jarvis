"""Add learning guide job tracking

Revision ID: 041_learning_guide_jobs
Revises: 040_learning_blueprints
Create Date: 2026-02-13

Adds:
- learning_guide_job table for background study-guide generation jobs
"""
from alembic import op


revision = "041_learning_guide_jobs"
down_revision = "040_learning_blueprints"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_guide_job (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            blueprint_id VARCHAR(36) NOT NULL REFERENCES learning_blueprint(id) ON DELETE CASCADE,
            status VARCHAR(50) DEFAULT 'queued',
            progress INTEGER DEFAULT 0,
            current_step TEXT,
            total_modules INTEGER DEFAULT 0,
            completed_modules INTEGER DEFAULT 0,
            artifacts_created INTEGER DEFAULT 0,
            model VARCHAR(255),
            error_message TEXT,
            meta JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        );
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_guide_job_user ON learning_guide_job (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_guide_job_blueprint ON learning_guide_job (blueprint_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_guide_job_status ON learning_guide_job (status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_learning_guide_job_created_at ON learning_guide_job (created_at);")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_learning_guide_job_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_learning_guide_job_status;")
    op.execute("DROP INDEX IF EXISTS ix_learning_guide_job_blueprint;")
    op.execute("DROP INDEX IF EXISTS ix_learning_guide_job_user;")
    op.execute("DROP TABLE IF EXISTS learning_guide_job;")

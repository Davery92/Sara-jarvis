"""Add candidate_skill table for agent-proposed skills

Revision ID: 042_candidate_skills
Revises: 041_learning_guide_jobs
Create Date: 2026-02-15

Adds:
- candidate_skill table for skills proposed by agents, pending review
"""
from alembic import op


revision = "042_candidate_skills"
down_revision = "041_learning_guide_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_skill (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            instructions TEXT,
            contexts JSONB DEFAULT '[]'::jsonb,
            priority INTEGER DEFAULT 50,
            status VARCHAR(50) DEFAULT 'pending',
            source_mission_id VARCHAR(36),
            source_task_id VARCHAR(36),
            vm_artifacts JSONB DEFAULT '{}'::jsonb,
            review_notes TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            reviewed_at TIMESTAMPTZ
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_skill_user_id ON candidate_skill(user_id);
        CREATE INDEX IF NOT EXISTS idx_candidate_skill_status ON candidate_skill(status);
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS candidate_skill;")

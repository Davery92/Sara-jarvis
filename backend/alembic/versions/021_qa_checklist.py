"""Add QA checklist tables

Revision ID: 021_qa_checklist
Revises: 020_project_tracker
Create Date: 2024-12-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '021_qa_checklist'
down_revision = '020_project_tracker'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # QA Checklist Items - per-project configurable test items
    op.create_table(
        'qa_checklist_item',
        sa.Column('id', sa.String, primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column('project_id', sa.String, sa.ForeignKey('dev_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String, sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('sort_order', sa.Integer, default=0),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Index for fast lookup by project
    op.create_index('ix_qa_checklist_item_project', 'qa_checklist_item', ['project_id', 'is_active', 'sort_order'])

    # QA Commit Results - stores the QA outcome for each commit
    op.create_table(
        'qa_commit_result',
        sa.Column('id', sa.String, primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column('commit_id', sa.String, sa.ForeignKey('git_commit.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.String, sa.ForeignKey('dev_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String, sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('checked_items', JSONB, default=list),  # List of checked item IDs
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('status', sa.String(20), default='pending'),  # pending, passed, failed, skipped
        sa.Column('tested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Index for finding QA results by commit
    op.create_index('ix_qa_commit_result_commit', 'qa_commit_result', ['commit_id'])
    # Index for finding pending QA by project
    op.create_index('ix_qa_commit_result_project_status', 'qa_commit_result', ['project_id', 'status'])
    # Unique constraint - one QA result per commit
    op.create_unique_constraint('uq_qa_commit_result_commit', 'qa_commit_result', ['commit_id'])


def downgrade() -> None:
    op.drop_table('qa_commit_result')
    op.drop_table('qa_checklist_item')

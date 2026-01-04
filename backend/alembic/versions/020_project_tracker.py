"""Project Development Tracker - Projects, Tasks, GitHub Integration

Revision ID: 020_project_tracker
Revises: 019_morning_brief_system
Create Date: 2025-12-06

This migration adds:
1. dev_project - Software development projects with GitHub integration
2. task_item - Task/issue tracking with Kanban status
3. git_commit - Commit history with task linking
4. git_branch - Branch tracking
5. pull_request - PR tracking
6. task_commit_link - Many-to-many link between tasks and commits

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy import inspect


revision = '020_project_tracker'
down_revision = '019_morning_brief_system'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # 1. Projects table
    if not table_exists('dev_project'):
        op.create_table(
            'dev_project',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('prefix', sa.String(10), nullable=False),  # e.g., "RN", "SARA"
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('tech_stack', sa.String(500), nullable=True),
            sa.Column('business_context', sa.String(500), nullable=True),

            # GitHub integration
            sa.Column('github_repo_owner', sa.String(255), nullable=True),
            sa.Column('github_repo_name', sa.String(255), nullable=True),
            sa.Column('github_installation_id', sa.String(255), nullable=True),

            # Status
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),

            # Counters (for task numbering)
            sa.Column('next_task_number', sa.Integer(), nullable=False, server_default='1'),

            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

            sa.PrimaryKeyConstraint('id')
        )

        # Indexes
        op.create_index('ix_dev_project_user', 'dev_project', ['user_id'])
        op.create_index('ix_dev_project_prefix', 'dev_project', ['user_id', 'prefix'], unique=True)

        # Foreign key
        op.create_foreign_key(
            'fk_dev_project_user',
            'dev_project',
            'app_user',
            ['user_id'],
            ['id'],
            ondelete='CASCADE'
        )

    # 2. Task Items table
    if not table_exists('task_item'):
        op.create_table(
            'task_item',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('project_id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('task_number', sa.Integer(), nullable=False),  # Auto-incremented per project
            sa.Column('title', sa.String(500), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),

            # Type: feature, bug, task, chore
            sa.Column('task_type', sa.String(20), nullable=False, server_default='task'),

            # Status: backlog, in_progress, in_qa, completed
            sa.Column('status', sa.String(20), nullable=False, server_default='backlog'),

            # Priority: low, medium, high, critical
            sa.Column('priority', sa.String(20), nullable=True),

            # Tags for categorization
            sa.Column('tags', ARRAY(sa.String()), nullable=True),

            # Ordering within status column
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),

            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),

            # Soft delete
            sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),

            sa.PrimaryKeyConstraint('id')
        )

        # Indexes
        op.create_index('ix_task_item_project', 'task_item', ['project_id'])
        op.create_index('ix_task_item_user', 'task_item', ['user_id'])
        op.create_index('ix_task_item_status', 'task_item', ['project_id', 'status'])
        op.create_index('ix_task_item_number', 'task_item', ['project_id', 'task_number'], unique=True)

        # Foreign keys
        op.create_foreign_key(
            'fk_task_item_project',
            'task_item',
            'dev_project',
            ['project_id'],
            ['id'],
            ondelete='CASCADE'
        )
        op.create_foreign_key(
            'fk_task_item_user',
            'task_item',
            'app_user',
            ['user_id'],
            ['id'],
            ondelete='CASCADE'
        )

    # 3. Git Commits table
    if not table_exists('git_commit'):
        op.create_table(
            'git_commit',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('project_id', sa.String(), nullable=False),
            sa.Column('sha', sa.String(40), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('author_name', sa.String(255), nullable=True),
            sa.Column('author_email', sa.String(255), nullable=True),
            sa.Column('committed_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('branch', sa.String(255), nullable=True),

            # File changes
            sa.Column('files_changed', JSONB, nullable=True),  # Array of filenames
            sa.Column('additions', sa.Integer(), nullable=True),
            sa.Column('deletions', sa.Integer(), nullable=True),

            # Raw webhook payload for reference
            sa.Column('raw_payload', JSONB, nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

            sa.PrimaryKeyConstraint('id')
        )

        # Indexes
        op.create_index('ix_git_commit_project', 'git_commit', ['project_id'])
        op.create_index('ix_git_commit_sha', 'git_commit', ['project_id', 'sha'], unique=True)
        op.create_index('ix_git_commit_date', 'git_commit', ['project_id', 'committed_at'])
        op.create_index('ix_git_commit_branch', 'git_commit', ['project_id', 'branch'])

        # Foreign key
        op.create_foreign_key(
            'fk_git_commit_project',
            'git_commit',
            'dev_project',
            ['project_id'],
            ['id'],
            ondelete='CASCADE'
        )

    # 4. Task-Commit Link table (many-to-many)
    if not table_exists('task_commit_link'):
        op.create_table(
            'task_commit_link',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('task_id', sa.String(), nullable=False),
            sa.Column('commit_id', sa.String(), nullable=False),
            sa.Column('auto_linked', sa.Boolean(), nullable=False, server_default='true'),  # vs manual
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('task_id', 'commit_id', name='uq_task_commit')
        )

        # Foreign keys
        op.create_foreign_key(
            'fk_task_commit_link_task',
            'task_commit_link',
            'task_item',
            ['task_id'],
            ['id'],
            ondelete='CASCADE'
        )
        op.create_foreign_key(
            'fk_task_commit_link_commit',
            'task_commit_link',
            'git_commit',
            ['commit_id'],
            ['id'],
            ondelete='CASCADE'
        )

    # 5. Git Branches table
    if not table_exists('git_branch'):
        op.create_table(
            'git_branch',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('project_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('last_commit_sha', sa.String(40), nullable=True),
            sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('is_merged', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('merged_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),

            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

            sa.PrimaryKeyConstraint('id')
        )

        # Indexes
        op.create_index('ix_git_branch_project', 'git_branch', ['project_id'])
        op.create_index('ix_git_branch_name', 'git_branch', ['project_id', 'name'], unique=True)

        # Foreign key
        op.create_foreign_key(
            'fk_git_branch_project',
            'git_branch',
            'dev_project',
            ['project_id'],
            ['id'],
            ondelete='CASCADE'
        )

    # 6. Pull Requests table
    if not table_exists('pull_request'):
        op.create_table(
            'pull_request',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('project_id', sa.String(), nullable=False),
            sa.Column('pr_number', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(500), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),

            # Status: open, closed, merged
            sa.Column('status', sa.String(20), nullable=False, server_default='open'),

            # Branches
            sa.Column('source_branch', sa.String(255), nullable=True),
            sa.Column('target_branch', sa.String(255), nullable=True),

            # Author
            sa.Column('author', sa.String(255), nullable=True),

            # Timestamps
            sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('merged_at', sa.DateTime(timezone=True), nullable=True),

            # Raw webhook payload
            sa.Column('raw_payload', JSONB, nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

            sa.PrimaryKeyConstraint('id')
        )

        # Indexes
        op.create_index('ix_pull_request_project', 'pull_request', ['project_id'])
        op.create_index('ix_pull_request_number', 'pull_request', ['project_id', 'pr_number'], unique=True)
        op.create_index('ix_pull_request_status', 'pull_request', ['project_id', 'status'])

        # Foreign key
        op.create_foreign_key(
            'fk_pull_request_project',
            'pull_request',
            'dev_project',
            ['project_id'],
            ['id'],
            ondelete='CASCADE'
        )

    # 7. PR-Task Link table (many-to-many)
    if not table_exists('pr_task_link'):
        op.create_table(
            'pr_task_link',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('pr_id', sa.String(), nullable=False),
            sa.Column('task_id', sa.String(), nullable=False),
            sa.Column('auto_linked', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('pr_id', 'task_id', name='uq_pr_task')
        )

        # Foreign keys
        op.create_foreign_key(
            'fk_pr_task_link_pr',
            'pr_task_link',
            'pull_request',
            ['pr_id'],
            ['id'],
            ondelete='CASCADE'
        )
        op.create_foreign_key(
            'fk_pr_task_link_task',
            'pr_task_link',
            'task_item',
            ['task_id'],
            ['id'],
            ondelete='CASCADE'
        )


def downgrade() -> None:
    # Drop in reverse order due to foreign key dependencies
    if table_exists('pr_task_link'):
        op.drop_table('pr_task_link')

    if table_exists('pull_request'):
        op.drop_table('pull_request')

    if table_exists('git_branch'):
        op.drop_table('git_branch')

    if table_exists('task_commit_link'):
        op.drop_table('task_commit_link')

    if table_exists('git_commit'):
        op.drop_table('git_commit')

    if table_exists('task_item'):
        op.drop_table('task_item')

    if table_exists('dev_project'):
        op.drop_table('dev_project')

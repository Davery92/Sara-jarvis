"""Add project files and folders tables for MinIO storage

Revision ID: 022_project_files
Revises: 021_qa_checklist
Create Date: 2025-12-06

This migration adds:
1. project_folder - Nested folder structure for project documents
2. project_file - File metadata with MinIO storage keys
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '022_project_files'
down_revision = '021_qa_checklist'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # 1. Project Folders table - supports nested hierarchy
    if not table_exists('project_folder'):
        op.create_table(
            'project_folder',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('project_id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('parent_id', sa.String(), nullable=True),  # Self-reference for nesting, null = root

            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

            sa.PrimaryKeyConstraint('id')
        )

        # Indexes
        op.create_index('ix_project_folder_project_parent', 'project_folder', ['project_id', 'parent_id'])
        op.create_index('ix_project_folder_user', 'project_folder', ['user_id'])

        # Foreign keys
        op.create_foreign_key(
            'fk_project_folder_project',
            'project_folder',
            'dev_project',
            ['project_id'],
            ['id'],
            ondelete='CASCADE'
        )
        op.create_foreign_key(
            'fk_project_folder_user',
            'project_folder',
            'app_user',
            ['user_id'],
            ['id'],
            ondelete='CASCADE'
        )
        op.create_foreign_key(
            'fk_project_folder_parent',
            'project_folder',
            'project_folder',
            ['parent_id'],
            ['id'],
            ondelete='CASCADE'
        )

    # 2. Project Files table - file metadata with MinIO storage
    if not table_exists('project_file'):
        op.create_table(
            'project_file',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('project_id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('folder_id', sa.String(), nullable=True),  # null = root folder
            sa.Column('filename', sa.String(500), nullable=False),  # Original filename
            sa.Column('storage_key', sa.String(1000), nullable=False),  # MinIO object key
            sa.Column('mime_type', sa.String(100), nullable=True),
            sa.Column('file_size', sa.Integer(), nullable=False),  # Size in bytes
            sa.Column('description', sa.Text(), nullable=True),  # Optional description

            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

            sa.PrimaryKeyConstraint('id')
        )

        # Indexes
        op.create_index('ix_project_file_project_folder', 'project_file', ['project_id', 'folder_id'])
        op.create_index('ix_project_file_user', 'project_file', ['user_id'])
        op.create_index('ix_project_file_storage_key', 'project_file', ['storage_key'], unique=True)

        # Foreign keys
        op.create_foreign_key(
            'fk_project_file_project',
            'project_file',
            'dev_project',
            ['project_id'],
            ['id'],
            ondelete='CASCADE'
        )
        op.create_foreign_key(
            'fk_project_file_user',
            'project_file',
            'app_user',
            ['user_id'],
            ['id'],
            ondelete='CASCADE'
        )
        op.create_foreign_key(
            'fk_project_file_folder',
            'project_file',
            'project_folder',
            ['folder_id'],
            ['id'],
            ondelete='SET NULL'  # If folder deleted, files move to root
        )


def downgrade() -> None:
    # Drop in reverse order due to foreign key dependencies
    if table_exists('project_file'):
        op.drop_table('project_file')

    if table_exists('project_folder'):
        op.drop_table('project_folder')

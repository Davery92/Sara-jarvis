"""Shadow Agent Rebuild - Machine registry, screenshot storage, session enhancements

Revision ID: 033_shadow_agent_rebuild
Revises: 032_sara_inner_monologue
Create Date: 2025-12-26

Tables:
- machine: Registered machines for shadow agent with activity tracking
- shadow_screenshot: Screenshot storage during shadow sessions
- Enhancements to shadow_session: machine_id, screenshot settings
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '033_shadow_agent_rebuild'
down_revision = '032_sara_inner_monologue'
branch_labels = None
depends_on = None


def upgrade():
    # ========================================
    # Table 1: machine
    # Registered machines for shadow agent
    # ========================================
    op.create_table('machine',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('device_id', sa.String(255), nullable=False, unique=True),

        # Machine info
        sa.Column('hostname', sa.String(255), nullable=True),
        sa.Column('platform', sa.String(50), nullable=True),  # windows, darwin, linux
        sa.Column('os_version', sa.String(100), nullable=True),

        # Activity tracking
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('activity_level', sa.String(20), server_default='idle'),  # idle, low, medium, high
        sa.Column('is_online', sa.Boolean, server_default='false'),

        # Agent capabilities
        sa.Column('capabilities', postgresql.JSONB, nullable=True),  # ["screenshot", "clipboard", ...]
        sa.Column('agent_version', sa.String(50), nullable=True),

        # Configuration
        sa.Column('screenshot_enabled', sa.Boolean, server_default='true'),
        sa.Column('screenshot_interval_seconds', sa.Integer, server_default='30'),
        sa.Column('clipboard_enabled', sa.Boolean, server_default='true'),
        sa.Column('terminal_enabled', sa.Boolean, server_default='true'),
        sa.Column('file_access_enabled', sa.Boolean, server_default='true'),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),

        sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE'),
    )

    op.create_index('ix_machine_user_id', 'machine', ['user_id'])
    op.create_index('ix_machine_device_id', 'machine', ['device_id'], unique=True)
    op.create_index('ix_machine_last_activity', 'machine', ['user_id', 'last_activity_at'])
    op.create_index('ix_machine_online', 'machine', ['user_id', 'is_online'])

    # ========================================
    # Table 2: shadow_screenshot
    # Screenshot storage during shadow sessions
    # ========================================
    op.create_table('shadow_screenshot',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), nullable=False),

        # Storage
        sa.Column('minio_key', sa.String(500), nullable=False),
        sa.Column('file_size_bytes', sa.Integer, nullable=True),

        # Context
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('window_title', sa.String(500), nullable=True),
        sa.Column('app_name', sa.String(100), nullable=True),
        sa.Column('image_hash', sa.String(64), nullable=True),  # For change detection (perceptual hash)

        # Privacy
        sa.Column('was_blurred', sa.Boolean, server_default='false'),
        sa.Column('blur_reason', sa.String(100), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),

        sa.ForeignKeyConstraint(['session_id'], ['shadow_session.id'], ondelete='CASCADE'),
    )

    op.create_index('ix_shadow_screenshot_session', 'shadow_screenshot', ['session_id'])
    op.create_index('ix_shadow_screenshot_timestamp', 'shadow_screenshot', ['session_id', 'timestamp'])
    op.create_index('ix_shadow_screenshot_hash', 'shadow_screenshot', ['session_id', 'image_hash'])

    # ========================================
    # Enhance shadow_session table
    # ========================================
    op.add_column('shadow_session',
        sa.Column('machine_id', sa.String(36), nullable=True))
    op.add_column('shadow_session',
        sa.Column('target_machine', sa.String(50), nullable=True))  # "auto" or specific device_id
    op.add_column('shadow_session',
        sa.Column('screenshots_enabled', sa.Boolean, server_default='true'))
    op.add_column('shadow_session',
        sa.Column('screenshot_interval_seconds', sa.Integer, server_default='30'))
    op.add_column('shadow_session',
        sa.Column('clipboard_enabled', sa.Boolean, server_default='true'))
    op.add_column('shadow_session',
        sa.Column('terminal_enabled', sa.Boolean, server_default='true'))
    op.add_column('shadow_session',
        sa.Column('file_access_enabled', sa.Boolean, server_default='true'))

    op.create_foreign_key(
        'fk_shadow_session_machine',
        'shadow_session', 'machine',
        ['machine_id'], ['id'],
        ondelete='SET NULL'
    )

    # ========================================
    # Enhance shadow_event table
    # ========================================
    op.add_column('shadow_event',
        sa.Column('screenshot_id', sa.String(36), nullable=True))
    op.add_column('shadow_event',
        sa.Column('content_hash', sa.String(64), nullable=True))  # For deduplication

    op.create_foreign_key(
        'fk_shadow_event_screenshot',
        'shadow_event', 'shadow_screenshot',
        ['screenshot_id'], ['id'],
        ondelete='SET NULL'
    )

    op.create_index('ix_shadow_event_content_hash', 'shadow_event', ['session_id', 'content_hash'])

    # ========================================
    # Enhance subconscious_state table
    # Add shadow session context fields
    # ========================================
    op.add_column('subconscious_state',
        sa.Column('recent_shadow_summary', sa.Text, nullable=True))
    op.add_column('subconscious_state',
        sa.Column('shadow_tasks', postgresql.JSONB, nullable=True))
    op.add_column('subconscious_state',
        sa.Column('shadow_decisions', postgresql.JSONB, nullable=True))
    op.add_column('subconscious_state',
        sa.Column('shadow_questions', postgresql.JSONB, nullable=True))
    op.add_column('subconscious_state',
        sa.Column('last_shadow_session_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('subconscious_state',
        sa.Column('shadow_focus_areas', postgresql.JSONB, nullable=True))


def downgrade():
    # Drop subconscious_state shadow columns
    op.drop_column('subconscious_state', 'shadow_focus_areas')
    op.drop_column('subconscious_state', 'last_shadow_session_at')
    op.drop_column('subconscious_state', 'shadow_questions')
    op.drop_column('subconscious_state', 'shadow_decisions')
    op.drop_column('subconscious_state', 'shadow_tasks')
    op.drop_column('subconscious_state', 'recent_shadow_summary')

    # Drop shadow_event enhancements
    op.drop_index('ix_shadow_event_content_hash')
    op.drop_constraint('fk_shadow_event_screenshot', 'shadow_event', type_='foreignkey')
    op.drop_column('shadow_event', 'content_hash')
    op.drop_column('shadow_event', 'screenshot_id')

    # Drop shadow_session enhancements
    op.drop_constraint('fk_shadow_session_machine', 'shadow_session', type_='foreignkey')
    op.drop_column('shadow_session', 'file_access_enabled')
    op.drop_column('shadow_session', 'terminal_enabled')
    op.drop_column('shadow_session', 'clipboard_enabled')
    op.drop_column('shadow_session', 'screenshot_interval_seconds')
    op.drop_column('shadow_session', 'screenshots_enabled')
    op.drop_column('shadow_session', 'target_machine')
    op.drop_column('shadow_session', 'machine_id')

    # Drop shadow_screenshot table
    op.drop_index('ix_shadow_screenshot_hash')
    op.drop_index('ix_shadow_screenshot_timestamp')
    op.drop_index('ix_shadow_screenshot_session')
    op.drop_table('shadow_screenshot')

    # Drop machine table
    op.drop_index('ix_machine_online')
    op.drop_index('ix_machine_last_activity')
    op.drop_index('ix_machine_device_id')
    op.drop_index('ix_machine_user_id')
    op.drop_table('machine')

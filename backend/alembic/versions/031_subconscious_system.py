"""Add subconscious system tables for Sara's mental model

Revision ID: 031_subconscious_system
Revises: 030_ios_calendar_sync
Create Date: 2025-12-19

Tables:
- subconscious_state: Single-row per user running mental model
- subconscious_nudge: Pending nudges with severity and expiry
- subconscious_log: History of state snapshots for pattern learning
- device_registration: Device tokens for Pi dashboard auth
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '031_subconscious_system'
down_revision = '030_ios_calendar_sync'
branch_labels = None
depends_on = None


def upgrade():
    # ========================================
    # Table 1: subconscious_state
    # Running mental model (single row per user, updated each cycle)
    # ========================================
    op.create_table('subconscious_state',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False, unique=True),

        # Meal tracking
        sa.Column('last_meal_type', sa.String(20), nullable=True),  # breakfast, lunch, dinner, snack
        sa.Column('last_meal_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('hours_since_meal', sa.Float, nullable=True),
        sa.Column('typical_meal_windows', postgresql.JSONB, nullable=True),  # {"breakfast": "07:00-09:00", ...}

        # Energy/mood inference
        sa.Column('inferred_energy_level', sa.Float, nullable=True),  # 0-1 scale
        sa.Column('inferred_mood', sa.String(50), nullable=True),  # positive, neutral, low, stressed
        sa.Column('message_velocity', sa.Float, nullable=True),  # messages per hour (recent)
        sa.Column('message_sentiment_avg', sa.Float, nullable=True),  # -1 to 1

        # Focus areas
        sa.Column('current_focus_areas', postgresql.JSONB, nullable=True),  # ["project X", "fitness", ...]
        sa.Column('active_threads', postgresql.JSONB, nullable=True),  # Open loops from conversations

        # Sleep tracking
        sa.Column('last_sleep_hours', sa.Float, nullable=True),
        sa.Column('last_sleep_quality', sa.String(20), nullable=True),  # good, fair, poor
        sa.Column('sleep_deficit_hours', sa.Float, nullable=True),

        # System health
        sa.Column('docker_health', postgresql.JSONB, nullable=True),  # {"backend": "healthy", ...}
        sa.Column('service_health', postgresql.JSONB, nullable=True),  # {"neo4j": "up", ...}
        sa.Column('llm_primary_status', sa.String(20), nullable=True),  # online, offline, slow
        sa.Column('llm_failover_status', sa.String(20), nullable=True),  # online, offline, slow
        sa.Column('llm_active_backend', sa.String(100), nullable=True),  # which backend URL is currently in use

        # Presence tracking
        sa.Column('last_presence_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('hours_since_presence', sa.Float, nullable=True),
        sa.Column('is_waking_hours', sa.Boolean, nullable=True),

        # Timestamps
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index('ix_subconscious_state_user', 'subconscious_state', ['user_id'], unique=True)

    # ========================================
    # Table 2: subconscious_nudge
    # Pending nudges with severity and expiry
    # ========================================
    op.create_table('subconscious_nudge',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),

        # Nudge content
        sa.Column('nudge_type', sa.String(50), nullable=False),  # missed_meal, bedtime, hydration, focus_break
        sa.Column('severity', sa.String(20), nullable=False),  # info, gentle, urgent
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('action_suggestion', sa.Text, nullable=True),  # Optional actionable suggestion

        # Delivery
        sa.Column('delivery_channel', sa.String(50), nullable=False),  # context_injection, passive_display, ios_push
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),

        # Lifecycle
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),  # pending, delivered, acknowledged, expired

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index('ix_subconscious_nudge_user_status', 'subconscious_nudge', ['user_id', 'status'])
    op.create_index('ix_subconscious_nudge_expires', 'subconscious_nudge', ['expires_at'])
    op.create_index('ix_subconscious_nudge_user_type', 'subconscious_nudge', ['user_id', 'nudge_type', 'created_at'])

    # ========================================
    # Table 3: subconscious_log
    # History of state snapshots for pattern learning
    # ========================================
    op.create_table('subconscious_log',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('snapshot_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state_snapshot', postgresql.JSONB, nullable=False),  # Full state at this point
        sa.Column('nudges_generated', postgresql.JSONB, nullable=True),  # Nudges created this cycle
        sa.Column('signals_processed', postgresql.JSONB, nullable=True),  # What data was analyzed
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index('ix_subconscious_log_user_time', 'subconscious_log', ['user_id', 'snapshot_at'])
    # Keep only recent logs (can be cleaned up periodically)
    op.create_index('ix_subconscious_log_created', 'subconscious_log', ['created_at'])

    # ========================================
    # Table 4: device_registration
    # Device tokens for Pi dashboard and other headless clients
    # ========================================
    op.create_table('device_registration',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('device_name', sa.String(100), nullable=False),
        sa.Column('device_token', sa.String(256), nullable=False, unique=True),
        sa.Column('device_type', sa.String(50), nullable=False),  # pi_dashboard, desktop_agent
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index('ix_device_registration_token', 'device_registration', ['device_token'], unique=True)
    op.create_index('ix_device_registration_user', 'device_registration', ['user_id'])


def downgrade():
    # Drop device_registration
    op.drop_index('ix_device_registration_user')
    op.drop_index('ix_device_registration_token')
    op.drop_table('device_registration')

    # Drop subconscious_log
    op.drop_index('ix_subconscious_log_created')
    op.drop_index('ix_subconscious_log_user_time')
    op.drop_table('subconscious_log')

    # Drop subconscious_nudge
    op.drop_index('ix_subconscious_nudge_user_type')
    op.drop_index('ix_subconscious_nudge_expires')
    op.drop_index('ix_subconscious_nudge_user_status')
    op.drop_table('subconscious_nudge')

    # Drop subconscious_state
    op.drop_index('ix_subconscious_state_user')
    op.drop_table('subconscious_state')

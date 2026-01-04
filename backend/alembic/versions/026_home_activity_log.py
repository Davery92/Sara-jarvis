"""Add home_activity_log table for Home Assistant integration

Revision ID: 026_home_activity_log
Revises: 025_enhance_dream_insights
Create Date: 2025-12-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = '026_home_activity_log'
down_revision = '025_enhance_dream_insights'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'home_activity_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('entity_id', sa.String(255), nullable=False),
        sa.Column('friendly_name', sa.String(255), nullable=True),
        sa.Column('domain', sa.String(50), nullable=False),
        sa.Column('from_state', sa.String(255), nullable=True),
        sa.Column('to_state', sa.String(255), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('context', JSONB, nullable=True),  # day_of_week, hour, etc.
        sa.Column('attributes', JSONB, nullable=True),  # Full HA attributes snapshot
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    # Index for querying by entity and time
    op.create_index(
        'idx_home_activity_entity_time',
        'home_activity_log',
        ['entity_id', 'changed_at']
    )

    # Index for time-range queries
    op.create_index(
        'idx_home_activity_changed_at',
        'home_activity_log',
        ['changed_at']
    )

    # Index for domain filtering
    op.create_index(
        'idx_home_activity_domain',
        'home_activity_log',
        ['domain', 'changed_at']
    )


def downgrade():
    op.drop_index('idx_home_activity_domain', table_name='home_activity_log')
    op.drop_index('idx_home_activity_changed_at', table_name='home_activity_log')
    op.drop_index('idx_home_activity_entity_time', table_name='home_activity_log')
    op.drop_table('home_activity_log')

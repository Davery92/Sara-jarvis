"""Add iOS calendar sync fields to calendar_event table

Revision ID: 030_ios_calendar_sync
Revises: 029_health_monitoring_system
Create Date: 2025-12-18

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '030_ios_calendar_sync'
down_revision = '029_health_monitoring_system'
branch_labels = None
depends_on = None


def upgrade():
    # Add iOS calendar sync columns to calendar_event table
    op.add_column('calendar_event', sa.Column('source', sa.String(50), server_default='sara', nullable=False))
    op.add_column('calendar_event', sa.Column('ios_event_id', sa.String(255), nullable=True))
    op.add_column('calendar_event', sa.Column('ios_calendar_id', sa.String(255), nullable=True))
    op.add_column('calendar_event', sa.Column('ios_calendar_name', sa.String(255), nullable=True))
    op.add_column('calendar_event', sa.Column('read_only', sa.Boolean(), server_default='false', nullable=False))

    # Create unique index for iOS event deduplication (per user + event_id + start_time)
    # Recurring events have the same ios_event_id but different start times
    op.create_index(
        'ix_calendar_event_ios_unique',
        'calendar_event',
        ['user_id', 'ios_event_id', 'start_time'],
        unique=True,
        postgresql_where=sa.text("ios_event_id IS NOT NULL")
    )

    # Index for filtering by source
    op.create_index('ix_calendar_event_source', 'calendar_event', ['source'])


def downgrade():
    op.drop_index('ix_calendar_event_source')
    op.drop_index('ix_calendar_event_ios_unique')
    op.drop_column('calendar_event', 'read_only')
    op.drop_column('calendar_event', 'ios_calendar_name')
    op.drop_column('calendar_event', 'ios_calendar_id')
    op.drop_column('calendar_event', 'ios_event_id')
    op.drop_column('calendar_event', 'source')

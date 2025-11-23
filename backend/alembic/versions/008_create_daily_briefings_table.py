"""create daily_briefings table

Revision ID: 008_daily_briefings
Revises: 007_proactive_suggestions
Create Date: 2025-11-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers
revision = '008_daily_briefings'
down_revision = '007_proactive_suggestions'
branch_labels = None
depends_on = None


def upgrade():
    # Create daily_briefing table
    op.create_table(
        'daily_briefing',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('briefing_type', sa.String(), nullable=False),  # morning, evening
        sa.Column('briefing_date', sa.Date(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),  # Markdown-formatted briefing
        sa.Column('data', JSON, nullable=False, server_default='{}'),  # Structured data
        sa.Column('delivered', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivery_method', sa.String(), nullable=True),  # push, email, chat
        sa.Column('read', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('generation_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_daily_briefing_user_id', 'daily_briefing', ['user_id'])
    op.create_index('ix_daily_briefing_type', 'daily_briefing', ['briefing_type'])
    op.create_index('ix_daily_briefing_date', 'daily_briefing', ['briefing_date'])
    op.create_index('ix_daily_briefing_user_date_type', 'daily_briefing',
                    ['user_id', 'briefing_date', 'briefing_type'], unique=True)
    op.create_index('ix_daily_briefing_delivered', 'daily_briefing', ['delivered'])

    # Create briefing_settings table
    op.create_table(
        'briefing_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('morning_enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('morning_time', sa.Time(), nullable=True, server_default='07:00:00'),
        sa.Column('evening_enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('evening_time', sa.Time(), nullable=True, server_default='21:00:00'),
        sa.Column('delivery_methods', JSON, nullable=False, server_default='["push"]'),  # push, email, chat
        sa.Column('include_weather', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('include_calendar', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('include_goals', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('include_suggestions', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_briefing_settings_user_id', 'briefing_settings', ['user_id'], unique=True)


def downgrade():
    op.drop_table('briefing_settings')
    op.drop_table('daily_briefing')

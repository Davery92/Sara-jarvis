"""Morning Brief System - News aggregation, weather, calendar integration

Revision ID: 019_morning_brief_system
Revises: 018_fitness_overhaul
Create Date: 2025-12-05

This migration adds:
1. morning_brief - Daily morning briefs with synthesized content and TTS audio

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect


revision = '019_morning_brief_system'
down_revision = '018_fitness_overhaul'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # Morning Brief Table
    if not table_exists('morning_brief'):
        op.create_table(
            'morning_brief',
            sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('brief_date', sa.Date(), nullable=False),

            # Content sections
            sa.Column('news_summary', sa.Text(), nullable=True),
            sa.Column('weather_summary', sa.Text(), nullable=True),
            sa.Column('calendar_summary', sa.Text(), nullable=True),
            sa.Column('full_text', sa.Text(), nullable=True),

            # Audio
            sa.Column('audio_path', sa.String(), nullable=True),
            sa.Column('audio_duration_seconds', sa.Float(), nullable=True),

            # Recovery section (generated on-demand)
            sa.Column('recovery_text', sa.Text(), nullable=True),
            sa.Column('recovery_audio_path', sa.String(), nullable=True),

            # Source data (for debugging/auditing)
            sa.Column('news_sources', JSONB, nullable=True),
            sa.Column('weather_data', JSONB, nullable=True),
            sa.Column('calendar_events', JSONB, nullable=True),

            # Timestamps
            sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('ntfy_sent_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('listened_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

            sa.PrimaryKeyConstraint('id')
        )

        # Index for fast lookup by user and date
        op.create_index(
            'ix_morning_brief_user_date',
            'morning_brief',
            ['user_id', 'brief_date'],
            unique=True
        )

        # Index for listing recent briefs
        op.create_index(
            'ix_morning_brief_user_created',
            'morning_brief',
            ['user_id', 'created_at']
        )

        # Foreign key to app_user table
        op.create_foreign_key(
            'fk_morning_brief_user',
            'morning_brief',
            'app_user',
            ['user_id'],
            ['id'],
            ondelete='CASCADE'
        )


def downgrade() -> None:
    if table_exists('morning_brief'):
        op.drop_table('morning_brief')

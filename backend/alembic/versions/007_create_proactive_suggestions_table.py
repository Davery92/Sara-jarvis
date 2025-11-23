"""create proactive suggestions table

Revision ID: 007_proactive_suggestions
Revises: 006_goals_tables
Create Date: 2025-11-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers
revision = '007_proactive_suggestions'
down_revision = '006_goals_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Create proactive_suggestion table
    op.create_table(
        'proactive_suggestion',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('suggestion_type', sa.String(), nullable=False),  # meal, workout, break, prep, etc.
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('action_data', JSON, nullable=False, server_default='{}'),  # Action to take if accepted
        sa.Column('confidence', sa.Float(), nullable=True),  # 0-1 confidence score
        sa.Column('priority', sa.Integer(), nullable=True, server_default='5'),  # 1-10
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),  # pending, accepted, dismissed
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),  # Suggestion expiry
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_proactive_suggestion_user_id', 'proactive_suggestion', ['user_id'])
    op.create_index('ix_proactive_suggestion_status', 'proactive_suggestion', ['status'])
    op.create_index('ix_proactive_suggestion_type', 'proactive_suggestion', ['suggestion_type'])
    op.create_index('ix_proactive_suggestion_user_status', 'proactive_suggestion', ['user_id', 'status'])
    op.create_index('ix_proactive_suggestion_expires_at', 'proactive_suggestion', ['expires_at'])

    # Create detected_pattern table
    op.create_table(
        'detected_pattern',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('pattern_type', sa.String(), nullable=False),  # weekly_habit, meal_timing, sleep_schedule, etc.
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('pattern_data', JSON, nullable=False, server_default='{}'),  # Pattern details
        sa.Column('confidence', sa.Float(), nullable=True),  # 0-1 confidence
        sa.Column('occurrences', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('first_detected', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_detected', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_detected_pattern_user_id', 'detected_pattern', ['user_id'])
    op.create_index('ix_detected_pattern_type', 'detected_pattern', ['pattern_type'])
    op.create_index('ix_detected_pattern_user_type', 'detected_pattern', ['user_id', 'pattern_type'])


def downgrade():
    op.drop_table('detected_pattern')
    op.drop_table('proactive_suggestion')

"""create event_log table

Revision ID: 001_event_log
Revises: None
Create Date: 2025-11-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision = '001_event_log'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create event_log table
    op.create_table(
        'event_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('payload', JSON, nullable=False, server_default='{}'),
        sa.Column('source', sa.String(), nullable=False, server_default='system'),
        sa.Column('metadata', JSON, nullable=False, server_default='{}'),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_event_log_event_id', 'event_log', ['event_id'], unique=True)
    op.create_index('ix_event_log_event_type', 'event_log', ['event_type'])
    op.create_index('ix_event_log_user_id', 'event_log', ['user_id'])
    op.create_index('ix_event_log_user_type', 'event_log', ['user_id', 'event_type'])
    op.create_index('ix_event_log_timestamp', 'event_log', ['timestamp'])


def downgrade():
    op.drop_table('event_log')

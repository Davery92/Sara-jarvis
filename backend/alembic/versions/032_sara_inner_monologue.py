"""Sara's Inner Monologue - Journal entries for experiential continuity

Revision ID: 032
Revises: 031
Create Date: 2025-12-22
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '032_sara_inner_monologue'
down_revision = '031_subconscious_system'
branch_labels = None
depends_on = None


def upgrade():
    # Sara's journal entries - her inner monologue
    op.create_table(
        'sara_journal',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),

        # Entry type: 'periodic' (every 30min), 'conversation_close', 'conversation_open'
        sa.Column('entry_type', sa.String(50), nullable=False, default='periodic'),

        # The journal entry itself - Sara's voice
        sa.Column('content', sa.Text(), nullable=False),

        # Structured context that informed this entry
        sa.Column('context', sa.JSON(), nullable=True),  # body_state, mood, recent_events

        # What she noticed since last entry
        sa.Column('observations', sa.Text(), nullable=True),

        # Her interpretation of the signals
        sa.Column('interpretation', sa.Text(), nullable=True),

        # Her emotional state (concerned, curious, pleased, etc.)
        sa.Column('emotional_state', sa.String(100), nullable=True),

        # Actions she took or held back on
        sa.Column('actions_taken', sa.Text(), nullable=True),

        # What she's watching for next
        sa.Column('watching_for', sa.Text(), nullable=True),

        # Link to conversation if this is a conversation entry
        sa.Column('conversation_id', sa.String(), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),

        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    )

    # Index for efficient retrieval
    op.create_index('idx_sara_journal_user_created', 'sara_journal', ['user_id', 'created_at'])
    op.create_index('idx_sara_journal_type', 'sara_journal', ['entry_type'])
    op.create_index('idx_sara_journal_conversation', 'sara_journal', ['conversation_id'])


def downgrade():
    op.drop_index('idx_sara_journal_conversation')
    op.drop_index('idx_sara_journal_type')
    op.drop_index('idx_sara_journal_user_created')
    op.drop_table('sara_journal')

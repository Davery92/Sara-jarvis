"""add_fitness_onboarding_sessions

Revision ID: d867121468cc
Revises: 331d698ff745
Create Date: 2025-09-02 15:45:26.945982

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd867121468cc'
down_revision: Union[str, Sequence[str], None] = '331d698ff745'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('fitness_onboarding_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('stage', sa.String(length=100), nullable=False, server_default='profile'),
        sa.Column('collected_answers', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('raw_answers', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('proposed_plan_draft_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
        sa.Column('current_question', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fitness_onboarding_sessions_user_id'), 'fitness_onboarding_sessions', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_fitness_onboarding_sessions_user_id'), table_name='fitness_onboarding_sessions')
    op.drop_table('fitness_onboarding_sessions')

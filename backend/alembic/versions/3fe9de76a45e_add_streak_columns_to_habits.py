"""add_streak_columns_to_habits

Revision ID: 3fe9de76a45e
Revises: 70161b318c97
Create Date: 2025-08-22 00:01:30.978579

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3fe9de76a45e'
down_revision: Union[str, Sequence[str], None] = '70161b318c97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add streak tracking columns to habits table
    op.add_column('habits', sa.Column('current_streak', sa.Integer(), nullable=True))
    op.add_column('habits', sa.Column('best_streak', sa.Integer(), nullable=True))
    op.add_column('habits', sa.Column('last_completed', sa.DateTime(), nullable=True))
    op.add_column('habits', sa.Column('vacation_from', sa.DateTime(), nullable=True))
    op.add_column('habits', sa.Column('vacation_to', sa.DateTime(), nullable=True))
    
    # Set default values for existing records
    op.execute("UPDATE habits SET current_streak = 0 WHERE current_streak IS NULL")
    op.execute("UPDATE habits SET best_streak = 0 WHERE best_streak IS NULL")
    
    # Make the columns non-nullable after setting defaults
    op.alter_column('habits', 'current_streak', nullable=False)
    op.alter_column('habits', 'best_streak', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove streak tracking columns
    op.drop_column('habits', 'vacation_to')
    op.drop_column('habits', 'vacation_from')
    op.drop_column('habits', 'last_completed')
    op.drop_column('habits', 'best_streak')
    op.drop_column('habits', 'current_streak')

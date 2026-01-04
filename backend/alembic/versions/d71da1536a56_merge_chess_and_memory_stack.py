"""merge chess and memory_stack

Revision ID: d71da1536a56
Revises: 014_chess_tables, 20250830_memory_stack
Create Date: 2025-11-27 22:54:36.210405

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd71da1536a56'
down_revision: Union[str, Sequence[str], None] = ('014_chess_tables', '20250830_memory_stack')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""merge_heads

Revision ID: 331d698ff745
Revises: 20250902_fitness_extensions, 225701a85ead
Create Date: 2025-09-02 15:44:52.721929

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '331d698ff745'
down_revision: Union[str, Sequence[str], None] = ('20250902_fitness_extensions', '225701a85ead')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

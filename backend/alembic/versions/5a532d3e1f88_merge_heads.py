"""Merge heads

Revision ID: 5a532d3e1f88
Revises: 161f0631bdce, 883ed5d7c483
Create Date: 2025-12-02 10:34:04.964484

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a532d3e1f88'
down_revision: Union[str, Sequence[str], None] = ('161f0631bdce', '883ed5d7c483')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

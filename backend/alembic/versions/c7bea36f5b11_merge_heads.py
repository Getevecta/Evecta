"""merge heads

Revision ID: c7bea36f5b11
Revises: 34cb4de034ba, 5f6664713cc0
Create Date: 2025-11-21 13:04:06.324728

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7bea36f5b11'
down_revision: Union[str, Sequence[str], None] = ('34cb4de034ba', '5f6664713cc0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

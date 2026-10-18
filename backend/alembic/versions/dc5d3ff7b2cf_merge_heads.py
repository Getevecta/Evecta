"""merge heads

Revision ID: dc5d3ff7b2cf
Revises: 10f1b9772c95, 4c72aac05014
Create Date: 2025-12-28 11:39:24.609902

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc5d3ff7b2cf'
down_revision: Union[str, Sequence[str], None] = ('10f1b9772c95', '4c72aac05014')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

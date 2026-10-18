"""merge multiple heads

Revision ID: 10f1b9772c95
Revises: 1941d162a370, 89b9da898a41
Create Date: 2025-12-21 14:36:41.755115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10f1b9772c95'
down_revision: Union[str, Sequence[str], None] = ('1941d162a370', '89b9da898a41')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

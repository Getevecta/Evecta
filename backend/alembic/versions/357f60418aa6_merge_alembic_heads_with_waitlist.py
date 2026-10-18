"""merge alembic heads with waitlist

Revision ID: 357f60418aa6
Revises: 1d6b313a537f, c41fcc03c60d
Create Date: 2026-01-21 14:25:42.141090

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '357f60418aa6'
down_revision: Union[str, Sequence[str], None] = ('1d6b313a537f', 'c41fcc03c60d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

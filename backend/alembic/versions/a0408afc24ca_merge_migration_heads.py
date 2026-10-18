"""merge migration heads

Revision ID: a0408afc24ca
Revises: k9c0d1e2f3g4, r2g3h4i5j6k7
Create Date: 2026-08-20 14:31:42.681176

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0408afc24ca'
down_revision: Union[str, Sequence[str], None] = ('k9c0d1e2f3g4', 'r2g3h4i5j6k7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""merge overture + campaign/mailbox migration heads

Revision ID: 04c93c160481
Revises: d5e6f7a8b9c0, da85a3f499e9
Create Date: 2026-07-28 14:50:41.445883

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '04c93c160481'
down_revision: Union[str, Sequence[str], None] = ('d5e6f7a8b9c0', 'da85a3f499e9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

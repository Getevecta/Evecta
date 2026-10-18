"""merge_all_heads

Revision ID: aead560cbe44
Revises: 870df9424937, add_starred_leads
Create Date: 2025-12-03 11:06:37.514793

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aead560cbe44'
down_revision: Union[str, Sequence[str], None] = ('870df9424937', 'add_starred_leads')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

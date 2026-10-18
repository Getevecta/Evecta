"""merge migration heads

Revision ID: af3814622d29
Revises: 5a532d3e1f88, 870df9424937
Create Date: 2025-12-02 16:57:58.622840

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'af3814622d29'
down_revision: Union[str, Sequence[str], None] = ('5a532d3e1f88', '870df9424937')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

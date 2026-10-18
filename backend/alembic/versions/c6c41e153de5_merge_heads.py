"""merge heads

Revision ID: c6c41e153de5
Revises: 8b65b6f31e9b, aead560cbe44
Create Date: 2025-12-10 13:11:55.659398

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6c41e153de5'
down_revision: Union[str, Sequence[str], None] = ('8b65b6f31e9b', 'aead560cbe44')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

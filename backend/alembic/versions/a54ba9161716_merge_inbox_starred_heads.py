"""merge_inbox_starred_heads

Revision ID: a54ba9161716
Revises: add_is_favorite_email_templates, add_starred_email_activities, c6c41e153de5, b2c3d4e5f6a7
Create Date: 2025-12-11 15:34:01.293974

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a54ba9161716'
down_revision: Union[str, Sequence[str], None] = ('add_is_favorite_email_templates', 'add_starred_email_activities', 'c6c41e153de5', 'b2c3d4e5f6a7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

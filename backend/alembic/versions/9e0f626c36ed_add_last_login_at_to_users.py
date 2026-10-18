"""add_last_login_at_to_users

Revision ID: 9e0f626c36ed
Revises: 69b3d85ad89b
Create Date: 2025-11-11 11:53:44.232840

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e0f626c36ed'
down_revision: Union[str, Sequence[str], None] = '69b3d85ad89b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'last_login_at')

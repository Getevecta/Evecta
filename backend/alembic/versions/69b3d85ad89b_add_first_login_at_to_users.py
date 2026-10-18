"""add_first_login_at_to_users

Revision ID: 69b3d85ad89b
Revises: e409b5cf5595
Create Date: 2025-11-11 11:27:12.680422

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69b3d85ad89b'
down_revision: Union[str, Sequence[str], None] = 'e409b5cf5595'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add first_login_at column to users table
    op.add_column('users', sa.Column('first_login_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove first_login_at column from users table
    op.drop_column('users', 'first_login_at')

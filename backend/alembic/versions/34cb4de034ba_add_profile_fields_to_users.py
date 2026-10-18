"""add_profile_fields_to_users

Revision ID: 34cb4de034ba
Revises: 9e0f626c36ed
Create Date: 2025-11-11 12:05:57.783351

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34cb4de034ba'
down_revision: Union[str, Sequence[str], None] = '9e0f626c36ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('full_name', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('department', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('location', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('website', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('bio', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('profile_image', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'profile_image')
    op.drop_column('users', 'bio')
    op.drop_column('users', 'website')
    op.drop_column('users', 'location')
    op.drop_column('users', 'department')
    op.drop_column('users', 'full_name')

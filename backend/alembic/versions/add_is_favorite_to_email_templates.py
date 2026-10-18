"""add_is_favorite_to_email_templates

Revision ID: add_is_favorite_email_templates
Revises: 870df9424937
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_is_favorite_email_templates'
down_revision: Union[str, Sequence[str], None] = '870df9424937'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add is_favorite column to email_templates table
    # First add as nullable, then update existing rows, then set not null
    op.add_column('email_templates', sa.Column('is_favorite', sa.Boolean(), nullable=True))
    # Update existing rows to False
    op.execute("UPDATE email_templates SET is_favorite = false WHERE is_favorite IS NULL")
    # Now make it not null with default
    op.alter_column('email_templates', 'is_favorite', nullable=False, server_default='false')


def downgrade() -> None:
    """Downgrade schema."""
    # Remove is_favorite column from email_templates table
    op.drop_column('email_templates', 'is_favorite')


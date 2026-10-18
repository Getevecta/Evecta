"""add starred to email_activities

Revision ID: add_starred_email_activities
Revises: 8258dd784d47
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_starred_email_activities'
down_revision: Union[str, Sequence[str], None] = '8258dd784d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add starred column to email_activities table
    op.add_column('email_activities', sa.Column('starred', sa.Boolean(), nullable=False, server_default='false'))
    op.create_index('ix_email_activities_starred', 'email_activities', ['starred'])


def downgrade() -> None:
    """Downgrade schema."""
    # Remove starred column from email_activities table
    op.drop_index('ix_email_activities_starred', table_name='email_activities')
    op.drop_column('email_activities', 'starred')


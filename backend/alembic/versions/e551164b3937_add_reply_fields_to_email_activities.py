"""add reply fields to email_activities

Revision ID: e551164b3937
Revises: e31f2c713845
Create Date: 2025-12-07 21:46:39.404103

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e551164b3937'
down_revision: Union[str, Sequence[str], None] = 'e31f2c713845'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

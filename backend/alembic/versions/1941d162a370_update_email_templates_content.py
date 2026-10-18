"""update email templates content

Revision ID: 1941d162a370
Revises: add_email_subscribed_leads
Create Date: 2025-12-21 12:26:45.557106

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1941d162a370'
down_revision: Union[str, Sequence[str], None] = 'add_email_subscribed_leads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

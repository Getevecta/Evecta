"""convert_lead_log_status_to_varchar

Revision ID: 18d35a14267f
Revises: 8b69d8731558
Create Date: 2026-01-07 11:30:11.990862

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '18d35a14267f'
down_revision: Union[str, Sequence[str], None] = '8b69d8731558'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

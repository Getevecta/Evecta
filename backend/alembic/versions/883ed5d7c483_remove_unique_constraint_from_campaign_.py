"""remove_unique_constraint_from_campaign_name

Revision ID: 883ed5d7c483
Revises: 7fcef134132d
Create Date: 2025-11-27 15:28:34.193741

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '883ed5d7c483'
down_revision: Union[str, Sequence[str], None] = '7fcef134132d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove unique constraint on campaign name to allow duplicate names."""
    # Drop the unique constraint
    op.drop_constraint('uq_campaign_user_name', 'campaigns', type_='unique')


def downgrade() -> None:
    """Re-add unique constraint on campaign name."""
    # Re-add the unique constraint
    op.create_unique_constraint('uq_campaign_user_name', 'campaigns', ['user_id', 'name'])

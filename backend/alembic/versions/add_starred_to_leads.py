"""add starred to leads

Revision ID: add_starred_leads
Revises: c254f1f45dc8
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_starred_leads'
down_revision: Union[str, Sequence[str], None] = '5a532d3e1f88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add starred column to leads table
    op.add_column('leads', sa.Column('starred', sa.Boolean(), nullable=False, server_default='false'))
    op.create_index('ix_leads_starred', 'leads', ['starred'])


def downgrade() -> None:
    """Downgrade schema."""
    # Remove starred column from leads table
    op.drop_index('ix_leads_starred', table_name='leads')
    op.drop_column('leads', 'starred')


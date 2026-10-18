"""add email_subscribed to leads

Revision ID: add_email_subscribed_leads
Revises: a54ba9161716
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_email_subscribed_leads'
down_revision: Union[str, Sequence[str], None] = 'a54ba9161716'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add email_subscribed column to leads table
    op.add_column('leads', sa.Column('email_subscribed', sa.Boolean(), nullable=False, server_default='true'))
    op.create_index('ix_leads_email_subscribed', 'leads', ['email_subscribed'])


def downgrade() -> None:
    """Downgrade schema."""
    # Remove email_subscribed column from leads table
    op.drop_index('ix_leads_email_subscribed', table_name='leads')
    op.drop_column('leads', 'email_subscribed')


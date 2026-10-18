"""add lead context fields (services, website_summary, business_description)

Revision ID: bc1ab59eca54
Revises: f1bb27dc185e
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'bc1ab59eca54'
down_revision: Union[str, Sequence[str], None] = 'f1bb27dc185e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('lead_log_leads', sa.Column('services', sa.Text(), nullable=True))
    op.add_column('lead_log_leads', sa.Column('website_summary', sa.Text(), nullable=True))
    op.add_column('lead_log_leads', sa.Column('business_description', sa.Text(), nullable=True))

    op.add_column('leads', sa.Column('services', sa.Text(), nullable=True))
    op.add_column('leads', sa.Column('website_summary', sa.Text(), nullable=True))
    op.add_column('leads', sa.Column('business_description', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('leads', 'business_description')
    op.drop_column('leads', 'website_summary')
    op.drop_column('leads', 'services')

    op.drop_column('lead_log_leads', 'business_description')
    op.drop_column('lead_log_leads', 'website_summary')
    op.drop_column('lead_log_leads', 'services')

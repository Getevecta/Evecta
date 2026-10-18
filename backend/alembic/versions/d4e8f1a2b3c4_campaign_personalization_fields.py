"""campaign personalization fields (tone + lead context snapshot)

Revision ID: d4e8f1a2b3c4
Revises: bc1ab59eca54
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e8f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "bc1ab59eca54"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("tone", sa.String(length=50), nullable=True))
    op.add_column("campaign_leads", sa.Column("services", sa.Text(), nullable=True))
    op.add_column("campaign_leads", sa.Column("website_summary", sa.Text(), nullable=True))
    op.add_column("campaign_leads", sa.Column("business_description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("campaign_leads", "business_description")
    op.drop_column("campaign_leads", "website_summary")
    op.drop_column("campaign_leads", "services")
    op.drop_column("campaigns", "tone")

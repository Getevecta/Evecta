"""backfill campaign_lead context snapshot from leads

Revision ID: e5f9a2b3c4d5
Revises: d4e8f1a2b3c4
Create Date: 2026-06-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "e5f9a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d4e8f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE campaign_leads AS cl
        SET
            services = l.services,
            website_summary = l.website_summary,
            business_description = l.business_description
        FROM leads AS l
        WHERE cl.lead_id = l.id
          AND (
            cl.services IS NULL
            OR cl.website_summary IS NULL
            OR cl.business_description IS NULL
          )
          AND (
            l.services IS NOT NULL
            OR l.website_summary IS NOT NULL
            OR l.business_description IS NOT NULL
          )
        """
    )


def downgrade() -> None:
    pass

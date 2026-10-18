"""add campaign launched_at column

Revision ID: k5e6f7a8b9c0
Revises: j4d5e6f7a8b9
Create Date: 2026-08-11 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "j4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Backfill from the earliest queued email job when available; otherwise updated_at
    # for non-draft campaigns. Drafts stay null.
    op.execute(
        """
        UPDATE campaigns c
        SET launched_at = COALESCE(
            (
                SELECT MIN(ej.created_at)
                FROM email_jobs ej
                WHERE ej.campaign_id = c.id
            ),
            c.updated_at
        )
        WHERE lower(c.status::text) IN ('ongoing', 'completed')
          AND c.launched_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("campaigns", "launched_at")

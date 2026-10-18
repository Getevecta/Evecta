"""Claim SMTP attempts and one successful activity per campaign+lead.

A worker can SMTP-send successfully and crash before marking the job SENT.
Celery then redelivers the same task. smtp_started_at records that SMTP was
about to run; the partial unique index stops a second non-failed activity row.

Revision ID: n8b9c0d1e2f3
Revises: m7a8b9c0d1e2
Create Date: 2026-08-19 11:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "m7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_jobs",
        sa.Column("smtp_started_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        sa.text(
            """
            DELETE FROM email_activities a
            WHERE a.status != 'FAILED'
              AND a.id NOT IN (
                SELECT kept.id
                FROM (
                  SELECT DISTINCT ON (campaign_id, lead_id) id
                  FROM email_activities
                  WHERE status != 'FAILED'
                  ORDER BY campaign_id, lead_id, sent_at ASC NULLS LAST, id ASC
                ) AS kept
              )
            """
        )
    )

    op.create_index(
        "uq_email_activity_campaign_lead_success",
        "email_activities",
        ["campaign_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text("status != 'FAILED'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_email_activity_campaign_lead_success",
        table_name="email_activities",
    )
    op.drop_column("email_jobs", "smtp_started_at")

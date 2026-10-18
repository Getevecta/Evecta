"""email activity tracking fix ses_message_id delivered_at first_opened_at open_count

Revision ID: 8443aa005e4c
Revises: c7d8e9f0a1b2
Create Date: 2026-07-03 14:30:01.489479

- ses_message_id: AWS-assigned MessageId captured from the SES v2 SendEmail
  response. SES events carry this exact value in mail.messageId, so it is the
  immutable primary matching key (message_id is no longer mutated by webhooks).
- delivered_at / first_opened_at: timestamps needed by the machine-open
  timing guard (open within seconds of delivery => scanner/proxy prefetch).
- open_count: number of recorded human opens (opened stays a rollup boolean).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8443aa005e4c'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "email_activities"


def _existing_columns(bind):
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(TABLE)}


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    existing = _existing_columns(bind)

    if "ses_message_id" not in existing:
        op.add_column(TABLE, sa.Column("ses_message_id", sa.String(length=255), nullable=True))
        op.create_index(
            op.f("ix_email_activities_ses_message_id"),
            TABLE,
            ["ses_message_id"],
            unique=True,
        )

    if "delivered_at" not in existing:
        op.add_column(TABLE, sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))

    if "first_opened_at" not in existing:
        op.add_column(TABLE, sa.Column("first_opened_at", sa.DateTime(timezone=True), nullable=True))

    if "open_count" not in existing:
        op.add_column(
            TABLE,
            sa.Column("open_count", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    existing = _existing_columns(bind)

    if "open_count" in existing:
        op.drop_column(TABLE, "open_count")
    if "first_opened_at" in existing:
        op.drop_column(TABLE, "first_opened_at")
    if "delivered_at" in existing:
        op.drop_column(TABLE, "delivered_at")
    if "ses_message_id" in existing:
        op.drop_index(op.f("ix_email_activities_ses_message_id"), table_name=TABLE)
        op.drop_column(TABLE, "ses_message_id")

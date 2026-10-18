"""add gemini_api_status_events table

Revision ID: h2b3c4d5e6f7
Revises: g1a2b3c4d5e6
Create Date: 2026-08-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "h2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "g1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gemini_api_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_kind", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("feature", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gemini_api_status_events_created_at",
        "gemini_api_status_events",
        ["created_at"],
    )
    op.create_index(
        "ix_gemini_api_status_events_error_kind",
        "gemini_api_status_events",
        ["error_kind"],
    )
    op.create_index(
        "ix_gemini_api_status_events_http_status",
        "gemini_api_status_events",
        ["http_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_gemini_api_status_events_http_status", table_name="gemini_api_status_events")
    op.drop_index("ix_gemini_api_status_events_error_kind", table_name="gemini_api_status_events")
    op.drop_index("ix_gemini_api_status_events_created_at", table_name="gemini_api_status_events")
    op.drop_table("gemini_api_status_events")

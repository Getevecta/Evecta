"""add external_api_usage_events table

Revision ID: j4d5e6f7a8b9
Revises: i3c4d5e6f7a8
Create Date: 2026-08-09 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "j4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "i3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "external_api_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("api_name", sa.String(length=64), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_cost_usd", sa.Float(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="success"),
        sa.Column("meta", sa.String(length=256), nullable=True),
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
        "ix_external_api_usage_events_created_at",
        "external_api_usage_events",
        ["created_at"],
    )
    op.create_index(
        "ix_external_api_usage_events_provider",
        "external_api_usage_events",
        ["provider"],
    )
    op.create_index(
        "ix_external_api_usage_events_api_name",
        "external_api_usage_events",
        ["api_name"],
    )
    op.create_index(
        "ix_external_api_usage_events_feature",
        "external_api_usage_events",
        ["feature"],
    )
    op.create_index(
        "ix_external_api_usage_events_user_id",
        "external_api_usage_events",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_api_usage_events_user_id",
        table_name="external_api_usage_events",
    )
    op.drop_index(
        "ix_external_api_usage_events_feature",
        table_name="external_api_usage_events",
    )
    op.drop_index(
        "ix_external_api_usage_events_api_name",
        table_name="external_api_usage_events",
    )
    op.drop_index(
        "ix_external_api_usage_events_provider",
        table_name="external_api_usage_events",
    )
    op.drop_index(
        "ix_external_api_usage_events_created_at",
        table_name="external_api_usage_events",
    )
    op.drop_table("external_api_usage_events")

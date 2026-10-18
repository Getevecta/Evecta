"""Subscription initial credit idempotency + plan_billing_interval on users.

Revision ID: c3f9a2b1e0d1
Revises: b7e2a1c0d9ef
Create Date: 2026-04-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3f9a2b1e0d1"
down_revision: Union[str, Sequence[str], None] = "b7e2a1c0d9ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_initial_credit_grants",
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("stripe_subscription_id"),
    )
    op.create_index(
        "ix_subscription_initial_credit_grants_user_id",
        "subscription_initial_credit_grants",
        ["user_id"],
        unique=False,
    )
    op.add_column(
        "users",
        sa.Column("plan_billing_interval", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "plan_billing_interval")
    op.drop_index(
        "ix_subscription_initial_credit_grants_user_id",
        table_name="subscription_initial_credit_grants",
    )
    op.drop_table("subscription_initial_credit_grants")

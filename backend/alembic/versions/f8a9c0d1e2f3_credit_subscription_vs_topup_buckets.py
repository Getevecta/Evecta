"""Split user_credits.balance into subscription vs top-up buckets.

Subscription credits reset each Stripe billing cycle (monthly or yearly invoice);
top-up credits persist until spent.

Revision ID: f8a9c0d1e2f3
Revises: ee21ba71f9cd
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "f8a9c0d1e2f3"
down_revision = "ee21ba71f9cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_credits",
        sa.Column("subscription_balance", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "user_credits",
        sa.Column("topup_balance", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE user_credits SET subscription_balance = COALESCE(balance, 0), topup_balance = 0"
    )
    op.drop_column("user_credits", "balance")
    op.alter_column("user_credits", "subscription_balance", server_default=None)
    op.alter_column("user_credits", "topup_balance", server_default=None)


def downgrade() -> None:
    op.add_column(
        "user_credits",
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE user_credits SET balance = COALESCE(subscription_balance, 0) + COALESCE(topup_balance, 0)"
    )
    op.drop_column("user_credits", "subscription_balance")
    op.drop_column("user_credits", "topup_balance")
    op.alter_column("user_credits", "balance", server_default=None)

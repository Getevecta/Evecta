"""Index credit history by user and newest-first created_at.

The history page filters one user and orders by created_at DESC with a limit.
The old user_id-only index still required a sort of every matching row.

Revision ID: o9c0d1e2f3a4
Revises: n8b9c0d1e2f3
Create Date: 2026-08-19 11:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "n8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "CREATE INDEX idx_credit_transactions_user_created "
            "ON credit_transactions (user_id, created_at DESC)"
        )
    )
    op.drop_index("ix_credit_transactions_user_id", table_name="credit_transactions")


def downgrade() -> None:
    op.create_index(
        "ix_credit_transactions_user_id",
        "credit_transactions",
        ["user_id"],
        unique=False,
    )
    op.drop_index(
        "idx_credit_transactions_user_created",
        table_name="credit_transactions",
    )

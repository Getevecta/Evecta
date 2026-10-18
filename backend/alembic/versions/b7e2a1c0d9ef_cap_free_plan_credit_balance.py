"""Cap user_credits.balance at free-tier allowance for free-plan users.

Free tier allowance is defined in app.core.plans PLANS['free']['credits'] (20).
Older signups may still hold 100; this aligns stored balance with current policy.

Revision ID: b7e2a1c0d9ef
Revises: aa1b4cff20db
Create Date: 2026-04-02
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2a1c0d9ef"
down_revision: Union[str, Sequence[str], None] = "aa1b4cff20db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep in sync with backend/app/core/plans.py PLANS["free"]["credits"]
FREE_PLAN_CREDIT_ALLOWANCE = 20


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE user_credits AS uc
        SET balance = LEAST(uc.balance, {FREE_PLAN_CREDIT_ALLOWANCE})
        FROM users AS u
        WHERE u.id = uc.user_id
          AND u.plan = 'free'
          AND uc.balance > {FREE_PLAN_CREDIT_ALLOWANCE};
        """
    )


def downgrade() -> None:
    # Cannot restore previous balances
    pass

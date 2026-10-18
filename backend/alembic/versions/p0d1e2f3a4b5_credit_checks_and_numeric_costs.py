"""Constrain credit pool/action values and store usage costs as Numeric.

Revision ID: p0d1e2f3a4b5
Revises: o9c0d1e2f3a4
Create Date: 2026-08-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "o9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_POOLS = ("lead", "email_gen", "outreach")
_ACTIONS = (
    "lead_found",
    "email_enriched",
    "email_scraped",
    "ai_draft",
    "spam_check",
    "email_sent",
    "subscription_grant",
    "topup",
    "refund",
    "free_plan_cap",
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE credit_transactions
            SET pool = 'lead'
            WHERE pool IS NOT NULL AND pool NOT IN ({_in_list(_POOLS)})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE user_credit_pools AS p
            SET pool = 'lead'
            WHERE p.pool NOT IN ({_in_list(_POOLS)})
              AND NOT EXISTS (
                SELECT 1 FROM user_credit_pools AS o
                WHERE o.user_id = p.user_id AND o.pool = 'lead'
              )
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DELETE FROM user_credit_pools
            WHERE pool NOT IN ({_in_list(_POOLS)})
              AND COALESCE(subscription_balance, 0) = 0
              AND COALESCE(topup_balance, 0) = 0
            """
        )
    )
    op.execute(sa.text("UPDATE credit_transactions SET action = lower(btrim(action))"))

    op.create_check_constraint(
        "ck_user_credit_pools_pool",
        "user_credit_pools",
        f"pool IN ({_in_list(_POOLS)})",
    )
    op.create_check_constraint(
        "ck_credit_transactions_pool",
        "credit_transactions",
        f"pool IS NULL OR pool IN ({_in_list(_POOLS)})",
    )
    # NOT VALID: existing unknown action spellings stay readable; new writes are rejected.
    op.execute(
        sa.text(
            f"""
            ALTER TABLE credit_transactions
            ADD CONSTRAINT ck_credit_transactions_action
            CHECK (action IN ({_in_list(_ACTIONS)})) NOT VALID
            """
        )
    )

    op.execute(
        sa.text(
            """
            ALTER TABLE ai_usage_events
            ALTER COLUMN input_rate_per_million TYPE NUMERIC(18, 10)
                USING input_rate_per_million::numeric,
            ALTER COLUMN output_rate_per_million TYPE NUMERIC(18, 10)
                USING output_rate_per_million::numeric,
            ALTER COLUMN estimated_cost_usd TYPE NUMERIC(18, 8)
                USING ROUND(estimated_cost_usd::numeric, 8)
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE external_api_usage_events
            ALTER COLUMN unit_cost_usd TYPE NUMERIC(18, 10)
                USING unit_cost_usd::numeric,
            ALTER COLUMN estimated_cost_usd TYPE NUMERIC(18, 8)
                USING ROUND(estimated_cost_usd::numeric, 8)
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE gemini_purchases
            ALTER COLUMN amount_usd TYPE NUMERIC(18, 8)
                USING ROUND(amount_usd::numeric, 8)
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE gemini_purchases ALTER COLUMN amount_usd TYPE FLOAT"))
    op.execute(
        sa.text(
            """
            ALTER TABLE external_api_usage_events
            ALTER COLUMN unit_cost_usd TYPE FLOAT,
            ALTER COLUMN estimated_cost_usd TYPE FLOAT
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE ai_usage_events
            ALTER COLUMN input_rate_per_million TYPE FLOAT,
            ALTER COLUMN output_rate_per_million TYPE FLOAT,
            ALTER COLUMN estimated_cost_usd TYPE FLOAT
            """
        )
    )
    op.drop_constraint("ck_credit_transactions_action", "credit_transactions", type_="check")
    op.drop_constraint("ck_credit_transactions_pool", "credit_transactions", type_="check")
    op.drop_constraint("ck_user_credit_pools_pool", "user_credit_pools", type_="check")

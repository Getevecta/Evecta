"""Credit pool/action constraints and display-denominator math."""
from sqlalchemy import CheckConstraint

from app.core.plans import CREDIT_COSTS, CREDIT_TRANSACTION_ACTIONS, POOLS
from app.models.credit import CreditTransaction, UserCreditPool
from app.services.credit_service import get_credit_display_denominator


def test_credit_transaction_actions_cover_spends_and_ledger():
    assert set(CREDIT_COSTS).issubset(CREDIT_TRANSACTION_ACTIONS)
    for action in ("subscription_grant", "topup", "refund", "free_plan_cap"):
        assert action in CREDIT_TRANSACTION_ACTIONS


def test_pool_and_action_check_constraints_match_plans():
    pool_sql = next(
        str(c.sqltext)
        for c in UserCreditPool.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == "ck_user_credit_pools_pool"
    )
    for pool in POOLS:
        assert f"'{pool}'" in pool_sql

    tx_pool_sql = next(
        str(c.sqltext)
        for c in CreditTransaction.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == "ck_credit_transactions_pool"
    )
    assert "pool IS NULL" in tx_pool_sql
    for pool in POOLS:
        assert f"'{pool}'" in tx_pool_sql

    action_sql = next(
        str(c.sqltext)
        for c in CreditTransaction.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == "ck_credit_transactions_action"
    )
    for action in CREDIT_TRANSACTION_ACTIONS:
        assert f"'{action}'" in action_sql


def test_display_denominator_uses_passed_topup_without_refetch():
    # Starter monthly lead allowance 500 + leftover top-up 40
    assert (
        get_credit_display_denominator("lead", "starter", "month", balance=12, topup_balance=40)
        == 540
    )
    # Balance above allowance+topup expands the bar
    assert (
        get_credit_display_denominator("lead", "starter", "month", balance=900, topup_balance=0)
        == 900
    )

"""Credit history is indexed by user_id + created_at DESC."""
from sqlalchemy import Index

from app.models.credit import CreditTransaction


def test_credit_history_has_user_created_composite_index():
    idx = next(
        i
        for i in CreditTransaction.__table__.indexes
        if i.name == "idx_credit_transactions_user_created"
    )
    assert isinstance(idx, Index)
    user_id_expr, created_at_expr = idx.expressions
    assert user_id_expr.name == "user_id"
    assert str(created_at_expr) == "created_at DESC"
    assert "ix_credit_transactions_user_id" not in {
        i.name for i in CreditTransaction.__table__.indexes
    }

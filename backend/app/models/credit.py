from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    desc,
)
from sqlalchemy.dialects.postgresql import UUID
from app.core.plans import CREDIT_TRANSACTION_ACTIONS, POOLS
from app.database.base import Base


def _sql_in_literals(values: tuple[str, ...]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


_POOL_IN = _sql_in_literals(POOLS)
_ACTION_IN = _sql_in_literals(CREDIT_TRANSACTION_ACTIONS)


class UserCreditPool(Base):
    """
    One row per (user, pool). Pools are independent balances: an action can only
    spend from its own pool (see app.core.plans.ACTION_POOLS). Each pool keeps the
    subscription-vs-topup split:
      - subscription_balance: plan / signup / renewal credits — reset each billing
        cycle (monthly or annual invoice); unused do not roll to next period.
      - topup_balance: one-time purchases; never cleared by subscription renewals.
    """
    __tablename__ = "user_credit_pools"
    __table_args__ = (
        UniqueConstraint("user_id", "pool", name="uq_user_credit_pools_user_pool"),
        CheckConstraint(f"pool IN ({_POOL_IN})", name="ck_user_credit_pools_pool"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    pool = Column(String(20), nullable=False)  # "lead" | "email_gen" | "outreach"
    subscription_balance = Column(Integer, default=0, nullable=False)
    topup_balance = Column(Integer, default=0, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    __table_args__ = (
        Index(
            "idx_credit_transactions_user_created",
            "user_id",
            desc("created_at"),
        ),
        CheckConstraint(
            f"pool IS NULL OR pool IN ({_POOL_IN})",
            name="ck_credit_transactions_pool",
        ),
        CheckConstraint(
            f"action IN ({_ACTION_IN})",
            name="ck_credit_transactions_action",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Integer, nullable=False)        # positive = added, negative = spent
    action = Column(String(50), nullable=False)     # "lead_found", "email_sent", "topup", etc.
    pool = Column(String(20), nullable=True)        # "lead" | "email_gen" | "outreach"; null only on pre-pool legacy rows
    description = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

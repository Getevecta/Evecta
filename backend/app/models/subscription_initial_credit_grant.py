from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base


class SubscriptionInitialCreditGrant(Base):
    """
    At most one initial credit grant per Stripe subscription id.
    Prevents double-grants when checkout.session.completed and confirm-checkout-session
    both run, or when invoice.paid fires for the first cycle with an unexpected reason.
    """

    __tablename__ = "subscription_initial_credit_grants"

    stripe_subscription_id = Column(String(255), primary_key=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

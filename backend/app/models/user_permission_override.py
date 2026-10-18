from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class UserPermissionOverride(Base):
    """
    Stores custom permission overrides for a specific user.

    - is_enabled = True  → force enable (custom ON)
    - is_enabled = False → force disable (custom OFF)
    - No record          → use role default
    """

    __tablename__ = "user_permission_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    permission_id = Column(
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # True  -> Custom Enabled
    # False -> Custom Disabled
    is_enabled = Column(Boolean, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    permission = relationship("Permission")
    user = relationship("User", back_populates="permission_overrides")

    __table_args__ = (
        UniqueConstraint("user_id", "permission_id", name="uq_user_permission_override"),
    )

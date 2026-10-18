from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    Boolean,
    DateTime,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base

# Avoid circular import
if TYPE_CHECKING:
    from app.models.user import User


class RefreshToken(Base):
    """
    Stores issued refresh tokens for tracking and revocation.
    """

    __tablename__ = "refresh_tokens"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Foreign key to user
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Unique token identifier (for revocation & rotation)
    jti = Column(UUID(as_uuid=True), unique=True, index=True, nullable=False)

    # Revocation status
    revoked = Column(Boolean, default=False, nullable=False)

    # Expiration timestamp (timezone-aware)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Creation timestamp (timezone-aware)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationship back to user
    user = relationship(
        "User",
        back_populates="refresh_tokens",
    )
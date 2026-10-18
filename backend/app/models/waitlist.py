from sqlalchemy import Column, String, DateTime, Index, func
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import uuid
from app.database.base import Base


class Waitlist(Base):
    """
    Represents a user who is on the waitlist.
    """

    __tablename__ = "waitlist"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    # Uniqueness is case-insensitive via ix_waitlist_email_lower.
    email = Column(String(255), index=True, nullable=False)
    username = Column(String(100), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_waitlist_email_lower", func.lower(email), unique=True),
    )
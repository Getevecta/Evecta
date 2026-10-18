from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, String, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class Domain(Base):
    __tablename__ = "domains"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    domain_name = Column(String, unique=True, nullable=False)

    daily_limit = Column(Integer, nullable=False, default=100)
    sent_today = Column(Integer, nullable=False, default=0)

    last_used = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    is_active = Column(Boolean, default=True)

    # Relationship → One domain has many mailboxes
    mailboxes = relationship(
        "Mailbox",
        back_populates="domain",
        cascade="all, delete-orphan",
        lazy="select",
    )

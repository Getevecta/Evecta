from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, ForeignKey, Index, Enum, text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from enum import Enum as PyEnum
from app.database.base import Base
import uuid


class MessageDirection(PyEnum):
    OUTBOUND = "outbound"  # We sent to lead
    INBOUND = "inbound"    # Lead replied to us


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Parent thread
    thread_id = Column(
        UUID(as_uuid=True),
        ForeignKey("email_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Which lead this message belongs to
    lead_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Denormalised for query convenience (avoids joining to thread)
    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    direction = Column(Enum(MessageDirection), nullable=False, index=True)

    # Who sent and who received
    sender_email = Column(String(255), nullable=True)
    recipient_email = Column(String(255), nullable=True)

    # Message body (HTML for OUTBOUND, plain text for INBOUND)
    body = Column(Text, nullable=True)

    # RFC822 threading headers
    # OUTBOUND: our generated Message-ID  e.g. <EV-uuid-campaign_id-lead_id@evecta>
    # INBOUND:  lead's Message-ID from their email client
    message_id = Column(String(512), nullable=True, index=True)

    # Set on replies — points to the previous message's message_id
    in_reply_to = Column(String(512), nullable=True, index=True)

    # Full RFC822 References chain (space-separated message IDs)
    references = Column(Text, nullable=True)

    # Which mailbox was used to send / which received this message
    mailbox_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mailboxes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Unread flag — False for INBOUND until the user opens the conversation
    is_read = Column(Boolean, default=True, nullable=False)

    # Backward compatibility — links back to existing EmailActivity row
    email_activity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("email_activities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    sent_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    thread = relationship("EmailThread", back_populates="messages", lazy="select")
    lead = relationship("Lead", backref="email_messages", lazy="select")
    mailbox = relationship("Mailbox", backref="email_messages", lazy="select")

    __table_args__ = (
        # Fast lookup: all messages for a lead inside a thread
        Index("idx_email_message_thread_lead", "thread_id", "lead_id"),
        # Fast lookup: match In-Reply-To → find original message
        Index("idx_email_message_message_id", "message_id"),
        Index("idx_email_message_in_reply_to", "in_reply_to"),
        # Unread messages per thread
        Index("idx_email_message_thread_unread", "thread_id", "is_read"),
        # Dedup guard: the same inbound message must be stored only once per
        # thread/lead — arbiter for ON CONFLICT DO NOTHING in reply fetch
        Index(
            "uq_email_messages_inbound_dedup",
            "thread_id", "lead_id", "message_id",
            unique=True,
            postgresql_where=text("direction = 'INBOUND' AND message_id IS NOT NULL"),
        ),
    )

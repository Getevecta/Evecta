from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


class MessageOut(BaseModel):
    id: str
    direction: str                    # "outbound" | "inbound"
    sender_email: Optional[str] = None
    recipient_email: Optional[str] = None
    body: Optional[str] = None
    message_id: Optional[str] = None
    sent_at: datetime
    is_read: bool

    class Config:
        from_attributes = True


class LeadConversationSummary(BaseModel):
    """One lead's latest reply — shown in the thread detail view."""
    lead_id: str
    lead_email: Optional[str] = None
    lead_name: Optional[str] = None
    lead_industry: Optional[str] = None
    lead_score: Optional[int] = None
    latest_reply: Optional[str] = None   # body of the most recent INBOUND message
    replied_at: Optional[datetime] = None
    is_read: bool                         # False if any INBOUND message is unread
    message_count: int                    # total messages in this lead's conversation
    has_user_replied: bool = False        # True if Evecta user sent a reply in this conversation


class ThreadOut(BaseModel):
    """One row in the inbox thread list — one per campaign."""
    id: str
    campaign_id: str
    campaign_name: str
    subject: Optional[str] = None
    last_message_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None  # thread created ≈ campaign send start
    total_recipients: int
    replied_count: int                    # distinct leads who replied
    opened_count: int = 0                 # emails opened by recipients (EmailActivity.opened)
    unread_reply_count: int
    user_reply_count: int = 0             # distinct leads the Evecta user replied to
    # Distinct leads the Evecta user has opened (all inbound read) but not replied to.
    # Used so a campaign can appear in Opened even if other leads are still Unread/Sent.
    opened_unreplied_count: int = 0
    is_starred: bool

    class Config:
        from_attributes = True


class ThreadDetailOut(BaseModel):
    """Thread detail — shows all leads who replied."""
    id: str
    campaign_id: str
    campaign_name: str
    subject: Optional[str] = None
    campaign_description: Optional[str] = None
    campaign_status: Optional[str] = None  # draft | ongoing | completed
    campaign_created_at: Optional[datetime] = None
    thread_started_at: Optional[datetime] = None  # inbox thread created ≈ send start
    total_recipients: int
    unread_reply_count: int
    is_starred: bool
    # USER-mode sending address only; omit/null for system mail
    email_sending_mode: Optional[str] = None
    sender_email: Optional[str] = None
    replies: List[LeadConversationSummary]


class LeadConversationOut(BaseModel):
    """Full message-by-message conversation with one lead."""
    lead_id: str
    lead_email: Optional[str] = None
    lead_name: Optional[str] = None
    messages: List[MessageOut]


class ThreadReplyRequest(BaseModel):
    message: str


class ThreadReplyOut(BaseModel):
    id: str
    message_id: Optional[str] = None
    sent_at: datetime
    sender_email: Optional[str] = None
    recipient_email: Optional[str] = None

    class Config:
        from_attributes = True

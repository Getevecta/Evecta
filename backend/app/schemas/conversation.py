from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ConversationMessage(BaseModel):
    type: str  # "sent" or "reply"
    text: Optional[str]
    timestamp: datetime
    message_id: str
    mailbox: Optional[str]  # mailbox used to send/receive


class ConversationThread(BaseModel):
    lead_id: str
    lead_email: str
    messages: list[ConversationMessage]

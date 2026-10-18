from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class InboxItem(BaseModel):
    lead_id: str
    lead_email: str
    lead_name: Optional[str]
    lead_address: Optional[str]
    lead_contact: Optional[str]
    lead_industry: Optional[str]
    lead_score: Optional[int]
    
    sent_email: Optional[str]
    last_reply: Optional[str]
    last_reply_time: Optional[datetime]

    last_sent_time: Optional[datetime]
    last_message_id: Optional[str]
    activity_id: str  # EmailActivity ID for starring

    campaign_id: str
    campaign_name: str
    starred: bool = False

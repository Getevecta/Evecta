from pydantic import BaseModel, UUID4

class EmailReplyCreate(BaseModel):
    activity_id: UUID4
    reply_text: str

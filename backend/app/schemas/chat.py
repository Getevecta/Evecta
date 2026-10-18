from pydantic import BaseModel, Field
from typing import Optional

# Shared validation for frontend-owned conversation ids (chat turns + New Chat reset).
_CONVERSATION_ID_FIELD = Field(
    default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
)


class ChatRequest(BaseModel):
    message: Optional[str] = None
    # Frontend-owned chat id. New Chat = a fresh conversation_id = a fresh thread, with no
    # server-side rotate race. Optional: older clients fall back to the per-user thread.
    # Validated (length + safe charset) so a tampered/oversized value can't bloat or
    # mis-key the checkpointer. UUIDs and the JS fallback ids both satisfy this.
    conversation_id: Optional[str] = _CONVERSATION_ID_FIELD


class ChatResetRequest(BaseModel):
    """Body for POST /chat/reset (New Chat).

    Pass the conversation_id being abandoned so the server can hard-delete that
    thread's checkpoints. Long-term memory (recent searches, prefs) is untouched.
    """
    conversation_id: Optional[str] = _CONVERSATION_ID_FIELD
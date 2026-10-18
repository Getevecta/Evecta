from pydantic import BaseModel, ConfigDict, Field, field_validator
from uuid import UUID
from typing import Optional, List
from enum import Enum

from app.utils.header_safety import (
    CONTENT_MAX_LENGTH,
    PROMPT_MAX_LENGTH,
    SUBJECT_MAX_LENGTH,
    optional_safe_text,
    require_safe_header,
)

class DraftType(str, Enum):
    TEMPLATE = "TEMPLATE"
    AI = "AI"
    MANUAL = "MANUAL"

class CampaignDraftBase(BaseModel):
    """Base schema for campaign drafts."""

    draft_type: DraftType = Field(...)
    template_id: Optional[UUID] = None
    email_subject: Optional[str] = Field(default=None, max_length=SUBJECT_MAX_LENGTH)
    email_content: Optional[str] = Field(default=None, max_length=CONTENT_MAX_LENGTH)
    ai_email_prompt: Optional[str] = Field(
        None,
        max_length=PROMPT_MAX_LENGTH,
        description="User's Step 3 AI compose prompt (separate from campaign description).",
    )

    @field_validator("draft_type", mode="before")
    def normalize_enum(cls, v):
        if isinstance(v, str):
            v = v.upper()
        return v

    @field_validator("email_subject")
    @classmethod
    def email_subject_no_newlines(cls, v: Optional[str]):
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            return None
        return require_safe_header(stripped, name="email_subject", max_length=SUBJECT_MAX_LENGTH)

    @field_validator("email_content")
    @classmethod
    def email_content_is_safe(cls, v: Optional[str]):
        return optional_safe_text(
            v, name="email_content", max_length=CONTENT_MAX_LENGTH, allow_newlines=True, strip=False
        )

    @field_validator("ai_email_prompt")
    @classmethod
    def prompt_is_safe(cls, v: Optional[str]):
        return optional_safe_text(
            v, name="ai_email_prompt", max_length=PROMPT_MAX_LENGTH, allow_newlines=True
        )
    
class CampaignDraftResponse(BaseModel):
    """Returned when reading a campaign draft."""
    model_config = ConfigDict(from_attributes=True)
    campaign_id: UUID
    draft_type: Optional[str] = None
    template_id: Optional[UUID] = None
    email_subject: Optional[str] = None
    email_content: Optional[str] = None
    tone: Optional[str] = None
    ai_email_prompt: Optional[str] = Field(
        None,
        description="User's Step 3 AI compose prompt used to generate this draft.",
    )

class AIDraftRequest(BaseModel):
    tone: str = Field(..., example="Friendly", description="Tone of the email, e.g., Friendly, Professional, Persuasive.")
    description: Optional[str] = Field(default=None, max_length=PROMPT_MAX_LENGTH)

    @field_validator("tone")
    @classmethod
    def tone_is_safe(cls, v: str):
        from app.utils.header_safety import NAME_MAX_LENGTH, require_safe_text

        return require_safe_text(v, name="tone", max_length=NAME_MAX_LENGTH, allow_newlines=False)

    @field_validator("description")
    @classmethod
    def description_is_safe(cls, v: Optional[str]):
        return optional_safe_text(
            v, name="description", max_length=PROMPT_MAX_LENGTH, allow_newlines=True
        )

class SpamCheckRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=SUBJECT_MAX_LENGTH)
    body: str = Field(..., max_length=CONTENT_MAX_LENGTH)
    fast_mode: Optional[bool] = Field(False, description="Skip validation and regeneration for faster results (recommended for manual/template modes)")

    @field_validator("subject")
    @classmethod
    def subject_no_newlines(cls, v: str):
        return require_safe_header(v, name="subject", max_length=SUBJECT_MAX_LENGTH)

    @field_validator("body")
    @classmethod
    def body_is_safe(cls, v: str):
        from app.utils.header_safety import require_safe_text

        return require_safe_text(
            v, name="body", max_length=CONTENT_MAX_LENGTH, allow_newlines=True, strip=False
        )

class SpamCheckResponse(BaseModel):
    spam_score: int = Field(..., ge=0, le=100, description="Spam score from 0 to 100")
    risk_level: str = Field(..., description="Risk level: Low, Medium, High, or Draft")
    reasons: List[str] = Field(default_factory=list, description="Reasons for the spam score")
    suggestions: List[str] = Field(default_factory=list, description="Suggestions to improve deliverability")
    rewritten_subject: Optional[str] = Field(None, description="Rewritten subject line")
    rewritten_body: Optional[str] = Field(None, description="Rewritten body content")
    rewritten_spam_score: Optional[int] = Field(None, ge=0, le=100, description="Validated spam score of rewritten content (always < 20)")
    rewritten_risk_level: Optional[str] = Field(None, description="Risk level of rewritten content (always Low)")

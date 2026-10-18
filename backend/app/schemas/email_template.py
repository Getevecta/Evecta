from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from app.models.email_template import TemplateCategory
from app.utils.header_safety import (
    CONTENT_MAX_LENGTH,
    NAME_MAX_LENGTH,
    SUBJECT_MAX_LENGTH,
    optional_safe_text,
    require_safe_header,
    require_safe_text,
)

# Base schema shared by others
class EmailTemplateBase(BaseModel):
    name: str = Field(..., max_length=NAME_MAX_LENGTH)
    subject: str = Field(..., max_length=SUBJECT_MAX_LENGTH)
    content: str = Field(..., max_length=CONTENT_MAX_LENGTH)
    category: Optional[TemplateCategory] = Field(None, example=TemplateCategory.PROFESSIONAL)

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, v: str):
        return require_safe_text(
            v, name="name", max_length=NAME_MAX_LENGTH, allow_newlines=False
        )

    @field_validator("subject")
    @classmethod
    def subject_no_newlines(cls, v: str):
        return require_safe_header(v, name="subject", max_length=SUBJECT_MAX_LENGTH)

    @field_validator("content")
    @classmethod
    def content_is_safe(cls, v: str):
        return require_safe_text(
            v, name="content", max_length=CONTENT_MAX_LENGTH, allow_newlines=True, strip=False
        )

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, v):
        """Handle invalid category values gracefully by converting them to None."""
        if v is None:
            return None
        # If it's already a valid TemplateCategory enum, return it
        if isinstance(v, TemplateCategory):
            return v
        # If it's a string, try to match it to valid enum values
        if isinstance(v, str):
            try:
                # Try to find matching enum value (case-insensitive)
                for enum_value in TemplateCategory:
                    if enum_value.value.lower() == v.lower():
                        return enum_value
                # If no match found, return None (invalid category)
                return None
            except (ValueError, AttributeError):
                return None
        return None

# Create schema
class EmailTemplateCreate(EmailTemplateBase):
    pass

# Update schema (all optional fields)
class EmailTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    subject: str | None = Field(default=None, max_length=SUBJECT_MAX_LENGTH)
    content: str | None = Field(default=None, max_length=CONTENT_MAX_LENGTH)
    category: TemplateCategory | None = None
    is_favorite: bool | None = None

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, v: str | None):
        return optional_safe_text(
            v, name="name", max_length=NAME_MAX_LENGTH, allow_newlines=False
        )

    @field_validator("subject")
    @classmethod
    def subject_no_newlines(cls, v: str | None):
        if v is None:
            return v
        return require_safe_header(v, name="subject", max_length=SUBJECT_MAX_LENGTH)

    @field_validator("content")
    @classmethod
    def content_is_safe(cls, v: str | None):
        return optional_safe_text(
            v, name="content", max_length=CONTENT_MAX_LENGTH, allow_newlines=True, strip=False
        )

# Response schema (for API responses)
class EmailTemplateResponse(EmailTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    is_favorite: Optional[bool] = False
    created_at: datetime
    updated_at: datetime

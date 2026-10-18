from pydantic import BaseModel, ConfigDict, Field, field_validator
from uuid import UUID
from datetime import datetime

from app.utils.header_safety import NAME_MAX_LENGTH, require_safe_text

class CampaignCategoryBase(BaseModel):
    name: str = Field(..., max_length=NAME_MAX_LENGTH, description="Name of the category")

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, v: str):
        return require_safe_text(v, name="name", max_length=NAME_MAX_LENGTH, allow_newlines=False)


class CampaignCategoryCreate(CampaignCategoryBase):
    """Used when creating a new campaign category."""
    pass


class CampaignCategoryUpdate(BaseModel):
    """Used when updating an existing category."""
    name: str = Field(..., max_length=NAME_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, v: str):
        return require_safe_text(v, name="name", max_length=NAME_MAX_LENGTH, allow_newlines=False)


class CampaignCategoryResponse(CampaignCategoryBase):
    """Returned when reading a category."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
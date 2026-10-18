from pydantic import BaseModel, ConfigDict, Field, field_validator
from uuid import UUID
from datetime import datetime

from app.utils.header_safety import NAME_MAX_LENGTH, require_safe_text

class CampaignGoalBase(BaseModel):
    name: str = Field(..., max_length=NAME_MAX_LENGTH, description="Name of the goal")

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, v: str):
        return require_safe_text(v, name="name", max_length=NAME_MAX_LENGTH, allow_newlines=False)


class CampaignGoalCreate(CampaignGoalBase):
    """Used when creating a new campaign goal."""
    pass

class CampaignGoalUpdate(BaseModel):
    """Used when updating an existing goal."""
    name: str = Field(..., max_length=NAME_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, v: str):
        return require_safe_text(v, name="name", max_length=NAME_MAX_LENGTH, allow_newlines=False)

class CampaignGoalResponse(CampaignGoalBase):
    """Returned when reading a goal."""

    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    created_at: datetime
    updated_at: datetime

from pydantic import BaseModel, Field
from typing import Optional


class SystemDomainCreate(BaseModel):
    name: str = Field(..., min_length=3)
    daily_limit: int = Field(default=5, gt=0)


class SystemDomainUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=3)
    daily_limit: Optional[int] = Field(default=None, gt=0)
    is_active: Optional[bool] = None

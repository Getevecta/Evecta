from pydantic import BaseModel, UUID4
from typing import Optional, List


# -------------------------
# Domain Schemas
# -------------------------
class DomainBase(BaseModel):
    domain_name: str
    daily_limit: int = 100
    is_active: bool = True


class DomainCreate(DomainBase):
    pass


class DomainUpdate(BaseModel):
    domain_name: Optional[str] = None
    daily_limit: Optional[int] = None
    is_active: Optional[bool] = None


class DomainRead(DomainBase):
    id: UUID4
    sent_today: int

    class Config:
        from_attributes = True



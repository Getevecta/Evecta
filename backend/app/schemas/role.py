from pydantic import BaseModel, UUID4
from typing import Optional, List

class PermissionBase(BaseModel):
    name: str
    description: Optional[str] = None
    group: Optional[str] = "General"

# FOR CREATE
class PermissionCreate(PermissionBase):
    pass

# FOR UPDATE
class PermissionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    group: Optional[str] = None

# FOR RESPONSE
class PermissionRead(PermissionBase):
    id: UUID4

    class Config:
        from_attributes = True


class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None

class RoleCreate(RoleBase):
    permission_ids: Optional[List[UUID4]] = []


class RoleRead(RoleBase):
    id: UUID4
    permissions: List[PermissionRead] = []

    class Config:
        from_attributes = True


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission_ids: Optional[List[UUID4]] = None
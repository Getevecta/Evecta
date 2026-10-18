from __future__ import annotations
import uuid
from sqlalchemy import Column, String, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.permission import role_permission 

class Role(Base):
    """
    Represents a role that aggregates multiple permissions, e.g. 'user', 'admin'.
    """
    __tablename__ = "roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)

    # many-to-many -> permissions
    permissions = relationship("Permission", secondary=role_permission, back_populates="roles")

    # one-to-many -> users
    users = relationship("User", back_populates="role_obj", cascade="save-update", passive_deletes=True)


    __table_args__ = (
        UniqueConstraint("name", name="uq_roles_name"),
        Index("ix_roles_name", "name"),
    )
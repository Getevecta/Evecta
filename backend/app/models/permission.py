from __future__ import annotations
from sqlalchemy import Column, String, Table, ForeignKey, UniqueConstraint,Index
import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base


# --- Association table: many-to-many between roles & permissions ---
role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    # Optional index for faster lookups
    Index("ix_role_permission_role_id", "role_id"),
    Index("ix_role_permission_permission_id", "permission_id"),
)


class Permission(Base):
    """ Represents a named capability like 'view_users', 'delete_users', etc. """
    __tablename__ = "permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)

    group = Column(String(100), nullable=False, default="General")
    roles = relationship("Role", secondary=role_permission, back_populates="permissions")

    __table_args__ = (
        UniqueConstraint("name", name="uq_permissions_name"),
    )
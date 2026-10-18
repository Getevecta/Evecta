from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard list envelope for campaign-related endpoints."""

    model_config = ConfigDict(from_attributes=True)

    current_page: int
    per_page: int
    total_items: int
    total_pages: int
    data: list[T] = Field(default_factory=list)

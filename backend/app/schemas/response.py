from typing import Any, Optional
from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    """
    Generic response model for all API endpoints.
    Used for standardized success/error responses.
    """

    status: str = Field(default="success", description="Response status (success/error)")
    message: str = Field(..., description="Short human-readable message")
    data: Optional[Any] = Field(default=None, description="Optional payload data")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message": "Leads saved to lead log.",
                "data": {
                    "log_id": "8e70b9e4-74de-4ac5-b49d-7486cc64e6a5",
                    "count": 5
                }
            }
        }

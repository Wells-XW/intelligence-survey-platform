"""User response schemas."""

from datetime import datetime

from pydantic import BaseModel


class UserResponse(BaseModel):
    """Public user profile returned by the API."""

    id: str
    email: str
    display_name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

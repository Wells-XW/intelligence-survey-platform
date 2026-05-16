"""User response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    """Public user profile returned by the API."""

    id: str
    email: str
    display_name: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
                    "email": "researcher@example.edu",
                    "display_name": "李雪松",
                    "is_active": True,
                    "created_at": "2026-09-01T08:00:00Z",
                }
            ]
        },
    )

"""Pydantic v2 schemas for Survey API.

PIPL Compliance Note: When collecting personal information via survey
JSON content, ensure data minimization principles are applied. Only
collect data that is strictly necessary for the research purpose.
See PRC Personal Information Protection Law, Articles 5-7.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


_SURVEY_JSON_EXAMPLE = {
    "pages": [
        {
            "name": "page1",
            "elements": [
                {
                    "type": "rating",
                    "name": "q1",
                    "title": "整体而言，您对当前学术诚信制度的满意度如何？",
                    "rateMin": 1,
                    "rateMax": 5,
                }
            ],
        }
    ]
}


class CreateSurveyRequest(BaseModel):
    """Request body for creating a new survey."""

    title: str = Field(default="未命名问卷", max_length=500)
    description: Optional[str] = None
    json_content: dict = Field(default_factory=lambda: {"pages": []})

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "学术诚信认知调查（2026春）",
                    "description": "面向硕博研究生的学术规范基线研究",
                    "json_content": _SURVEY_JSON_EXAMPLE,
                }
            ]
        }
    )


class UpdateSurveyRequest(BaseModel):
    """Request body for updating an existing survey."""

    title: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = None
    json_content: Optional[dict] = None
    status: Optional[str] = None  # draft | published | closed
    expected_version: Optional[int] = Field(
        default=None,
        description="Optimistic lock: client's expected version.  "
        "409 Conflict if server version differs.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "学术诚信认知调查（2026春・修订）",
                    "status": "published",
                    "expected_version": 3,
                }
            ]
        }
    )


class SurveyResponse(BaseModel):
    """Full survey response including all fields."""

    id: str
    owner_id: Optional[str] = None
    title: str
    description: Optional[str]
    json_content: dict
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "owner_id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
                    "title": "学术诚信认知调查（2026春）",
                    "description": "面向硕博研究生的学术规范基线研究",
                    "json_content": _SURVEY_JSON_EXAMPLE,
                    "status": "published",
                    "version": 4,
                    "created_at": "2026-09-01T08:00:00Z",
                    "updated_at": "2026-09-15T10:23:00Z",
                }
            ]
        },
    )


class SurveyListItem(BaseModel):
    """Abbreviated survey info for list views (without full JSON content)."""

    id: str
    title: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "title": "学术诚信认知调查（2026春）",
                    "status": "published",
                    "version": 4,
                    "created_at": "2026-09-01T08:00:00Z",
                    "updated_at": "2026-09-15T10:23:00Z",
                }
            ]
        },
    )

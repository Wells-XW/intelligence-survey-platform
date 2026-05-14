"""Pydantic v2 schemas for Survey API.

PIPL Compliance Note: When collecting personal information via survey
JSON content, ensure data minimization principles are applied. Only
collect data that is strictly necessary for the research purpose.
See PRC Personal Information Protection Law, Articles 5-7.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateSurveyRequest(BaseModel):
    """Request body for creating a new survey."""

    title: str = Field(default="未命名问卷", max_length=500)
    description: Optional[str] = None
    json_content: dict = Field(default_factory=lambda: {"pages": []})


class UpdateSurveyRequest(BaseModel):
    """Request body for updating an existing survey."""

    title: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = None
    json_content: Optional[dict] = None
    status: Optional[str] = None  # draft | published | closed


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

    model_config = {"from_attributes": True}


class SurveyListItem(BaseModel):
    """Abbreviated survey info for list views (without full JSON content)."""

    id: str
    title: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

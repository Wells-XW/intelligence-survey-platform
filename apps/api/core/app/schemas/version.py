"""Pydantic v2 schemas for survey version history."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VersionListItem(BaseModel):
    """Abbreviated version info for list views."""

    id: str
    version: int
    title: str
    creator_name: Optional[str] = None
    creator_id: Optional[str] = None
    changelog: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VersionDetail(BaseModel):
    """Full version snapshot including complete JSON content."""

    id: str
    version: int
    title: str
    description: Optional[str] = None
    json_content: dict
    creator_name: Optional[str] = None
    creator_id: Optional[str] = None
    changelog: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RestoreVersionRequest(BaseModel):
    """Request body for restoring a version."""

    changelog: Optional[str] = Field(
        default=None, description="Optional note e.g. 'Restored from version 3'"
    )


class VersionDiffResponse(BaseModel):
    """Unified diff between two versions."""

    from_version: VersionListItem
    to_version: VersionListItem
    diff_text: str

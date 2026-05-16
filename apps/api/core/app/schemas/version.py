"""Pydantic v2 schemas for survey version history."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


_VERSION_LIST_EXAMPLE = {
    "id": "9f1e6c2a-4d2c-4a11-83b0-7384d9a84f3b",
    "version": 4,
    "title": "学术诚信认知调查（2026春・修订）",
    "creator_name": "李雪松",
    "creator_id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
    "changelog": "Tightened consent wording; reverse-coded item 5",
    "created_at": "2026-09-15T10:23:00Z",
}


class VersionListItem(BaseModel):
    """Abbreviated version info for list views."""

    id: str
    version: int
    title: str
    creator_name: Optional[str] = None
    creator_id: Optional[str] = None
    changelog: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [_VERSION_LIST_EXAMPLE]},
    )


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

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    **_VERSION_LIST_EXAMPLE,
                    "description": "面向硕博研究生的学术规范基线研究",
                    "json_content": {
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
                    },
                }
            ]
        },
    )


class RestoreVersionRequest(BaseModel):
    """Request body for restoring a version."""

    changelog: Optional[str] = Field(
        default=None, description="Optional note e.g. 'Restored from version 3'"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"changelog": "Restored from version 3"}]
        }
    )


class VersionDiffResponse(BaseModel):
    """Unified diff between two versions."""

    from_version: VersionListItem
    to_version: VersionListItem
    diff_text: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "from_version": _VERSION_LIST_EXAMPLE,
                    "to_version": {
                        **_VERSION_LIST_EXAMPLE,
                        "version": 5,
                        "changelog": "Added prefer-not-to-say option to Q3",
                    },
                    "diff_text": (
                        "--- Version 4\n"
                        "+++ Version 5\n"
                        "@@ -3,4 +3,5 @@\n"
                        "       \"choices\": [\n"
                        "         \"非常同意\",\n"
                        "         \"同意\",\n"
                        "+        \"不便回答\",\n"
                        "         \"不同意\",\n"
                    ),
                }
            ]
        }
    )

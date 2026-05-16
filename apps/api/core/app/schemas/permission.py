"""Pydantic v2 schemas for permission management and invitations."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Permission Management ──────────────────────────────────────────────


_PERMISSION_DETAIL_EXAMPLE = {
    "id": "f3b9f1e6-c2a4-4d2c-8a11-d3b0738499a8",
    "user_id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
    "user_email": "co.researcher@example.edu",
    "user_display_name": "王明远",
    "role": "editor",
    "created_at": "2026-09-15T10:23:00Z",
}


class PermissionDetail(BaseModel):
    """A single permission entry with user info."""

    id: str
    user_id: str
    user_email: str
    user_display_name: str
    role: Literal["owner", "editor", "viewer"]
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [_PERMISSION_DETAIL_EXAMPLE]},
    )


class GrantPermissionRequest(BaseModel):
    """Request body for granting a permission to a user."""

    user_id: str
    role: Literal["editor", "viewer"] = "viewer"

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
                    "role": "editor",
                }
            ]
        }
    )


class UpdatePermissionRoleRequest(BaseModel):
    """Request body for updating a permission's role."""

    role: Literal["editor", "viewer"]

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"role": "viewer"}]}
    )


# ── Invitations ────────────────────────────────────────────────────────


class CreateInvitationRequest(BaseModel):
    """Request body for sending a collaboration invitation."""

    email: str = Field(max_length=320)
    role: Literal["editor", "viewer"] = "viewer"

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "co.researcher@example.edu",
                    "role": "editor",
                }
            ]
        }
    )


_INVITATION_EXAMPLE = {
    "id": "1e6c2a4d-2c8a-411d-b073-84d9a84f3b9f",
    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
    "email": "co.researcher@example.edu",
    "role": "editor",
    "status": "pending",
    "token": "Y3lwR0szbW1xdWZUcXJZdF9YYUJUVmRyV3lqM3lEbzU",
    "invite_url": (
        "https://intelligence-survey.example.com/invite/"
        "Y3lwR0szbW1xdWZUcXJZdF9YYUJUVmRyV3lqM3lEbzU"
    ),
    "expires_at": "2026-09-22T10:23:00Z",
    "created_at": "2026-09-15T10:23:00Z",
}


class InvitationResponse(BaseModel):
    """Public invitation information."""

    id: str
    survey_id: str
    email: str
    role: Literal["editor", "viewer"]
    status: Literal["pending", "accepted", "declined", "expired"]
    token: str
    invite_url: str
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [_INVITATION_EXAMPLE]},
    )


class InvitationAcceptResponse(BaseModel):
    """Response after accepting an invitation."""

    permission: PermissionDetail
    survey_title: str
    survey_id: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "permission": _PERMISSION_DETAIL_EXAMPLE,
                    "survey_title": "学术诚信认知调查（2026春）",
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                }
            ]
        }
    )


# ── User Search ────────────────────────────────────────────────────────


class UserSearchItem(BaseModel):
    """Minimal user info for search results."""

    id: str
    email: str
    display_name: str

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
                    "email": "co.researcher@example.edu",
                    "display_name": "王明远",
                }
            ]
        },
    )

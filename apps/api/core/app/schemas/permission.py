"""Pydantic v2 schemas for permission management and invitations."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, EmailStr


# ── Permission Management ──────────────────────────────────────────────


class PermissionDetail(BaseModel):
    """A single permission entry with user info."""

    id: str
    user_id: str
    user_email: str
    user_display_name: str
    role: Literal["owner", "editor", "viewer"]
    created_at: datetime

    model_config = {"from_attributes": True}


class GrantPermissionRequest(BaseModel):
    """Request body for granting a permission to a user."""

    user_id: str
    role: Literal["editor", "viewer"] = "viewer"


class UpdatePermissionRoleRequest(BaseModel):
    """Request body for updating a permission's role."""

    role: Literal["editor", "viewer"]


# ── Invitations ────────────────────────────────────────────────────────


class CreateInvitationRequest(BaseModel):
    """Request body for sending a collaboration invitation."""

    email: str = Field(max_length=320)
    role: Literal["editor", "viewer"] = "viewer"


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

    model_config = {"from_attributes": True}


class InvitationAcceptResponse(BaseModel):
    """Response after accepting an invitation."""

    permission: PermissionDetail
    survey_title: str
    survey_id: str


# ── User Search ────────────────────────────────────────────────────────


class UserSearchItem(BaseModel):
    """Minimal user info for search results."""

    id: str
    email: str
    display_name: str

    model_config = {"from_attributes": True}

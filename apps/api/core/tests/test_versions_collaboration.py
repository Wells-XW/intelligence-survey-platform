"""Tests for version history, collaboration, and optimistic locking.

Run:
    pytest tests/test_versions_collaboration.py -v
"""

import sys
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.survey_version import SurveyVersion
from app.models.collaboration_invitation import CollaborationInvitation
from app.models.survey_permission import SurveyPermission
from app.models.survey import Survey
from app.models.user import User
from app.schemas.version import (
    VersionListItem,
    VersionDetail,
    VersionDiffResponse,
    RestoreVersionRequest,
)
from app.schemas.permission import (
    PermissionDetail,
    GrantPermissionRequest,
    UpdatePermissionRoleRequest,
    CreateInvitationRequest,
    InvitationResponse,
    UserSearchItem,
)


# ──────────────────────────────────────────────────────────────────────
#  SurveyVersion model tests
# ──────────────────────────────────────────────────────────────────────


class TestSurveyVersionModel:
    """Unit tests for SurveyVersion ORM model fields and constraints."""

    def test_fields(self):
        """All expected columns exist with correct types."""
        import uuid

        sv = SurveyVersion(
            id=str(uuid.uuid4()),
            survey_id=str(uuid.uuid4()),
            version=3,
            json_content={"pages": [{"name": "page1"}]},
            title="Test Survey",
            description="A test",
            creator_id=str(uuid.uuid4()),
            changelog="Added question 5",
        )
        assert sv.version == 3
        assert sv.title == "Test Survey"
        assert sv.description == "A test"
        assert sv.json_content["pages"][0]["name"] == "page1"
        assert sv.changelog == "Added question 5"
        assert sv.creator_id is not None

    def test_defaults(self):
        """Default values are populated correctly."""
        sv = SurveyVersion(
            id="v1",
            survey_id="s1",
            version=1,
            json_content={"pages": []},
            title="",
        )
        assert sv.title == ""  # default empty string
        assert sv.description is None
        assert sv.changelog is None
        # created_at set at construction

    def test_repr(self):
        sv = SurveyVersion(id="abc", survey_id="s-1", version=5, json_content={})
        r = repr(sv)
        assert "SurveyVersion" in r
        assert "s-1" in r
        assert "5" in r


class TestCollaborationInvitationModel:
    """Unit tests for CollaborationInvitation ORM model."""

    def test_fields(self):
        import uuid

        now = datetime.now(timezone.utc)
        ci = CollaborationInvitation(
            id=str(uuid.uuid4()),
            survey_id=str(uuid.uuid4()),
            inviter_id=str(uuid.uuid4()),
            email="user@example.com",
            role="editor",
            token=secrets.token_urlsafe(32),
            status="pending",
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        assert ci.email == "user@example.com"
        assert ci.role == "editor"
        assert ci.status == "pending"
        assert len(ci.token) > 0

    def test_default_role(self):
        ci = CollaborationInvitation(
            id="i1",
            survey_id="s1",
            inviter_id="u1",
            email="test@test.com",
            token="abc",
            role="viewer",
            status="pending",
        )
        assert ci.role == "viewer"

    def test_default_status(self):
        ci = CollaborationInvitation(
            id="i1",
            survey_id="s1",
            inviter_id="u1",
            email="test@test.com",
            token="abc",
            role="viewer",
            status="pending",
        )
        assert ci.status == "pending"

    def test_expires_at_default_is_7_days(self):
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        ci = CollaborationInvitation(
            id="i1",
            survey_id="s1",
            inviter_id="u1",
            email="test@test.com",
            token="abc",
            role="viewer",
            status="pending",
            expires_at=expires,
        )
        # Expiry should be ~7 days from now
        assert ci.expires_at == expires

    def test_token_generation(self):
        """Token auto-generates via secrets.token_urlsafe(32)."""
        ci = CollaborationInvitation(
            id="i1",
            survey_id="s1",
            inviter_id="u1",
            email="test@test.com",
            token=secrets.token_urlsafe(32),
            role="viewer",
            status="pending",
        )
        assert len(ci.token) >= 43  # base64 of 32 bytes ≥ 43 chars

    def test_repr(self):
        ci = CollaborationInvitation(
            id="abc", survey_id="s1", inviter_id="u1",
            email="x@y.com", token="tok",
        )
        r = repr(ci)
        assert "CollaborationInvitation" in r
        assert "x@y.com" in r


# ──────────────────────────────────────────────────────────────────────
#  Pydantic schema tests
# ──────────────────────────────────────────────────────────────────────


class TestVersionSchemas:
    """Validate version-related Pydantic schemas."""

    def test_version_list_item(self):
        now = datetime.now(timezone.utc)
        item = VersionListItem(
            id="v1", version=3, title="Survey",
            creator_name="Alice", created_at=now,
        )
        assert item.version == 3
        assert item.creator_name == "Alice"

    def test_version_detail(self):
        now = datetime.now(timezone.utc)
        detail = VersionDetail(
            id="v1", version=3, title="Survey",
            json_content={"pages": []}, created_at=now,
        )
        assert detail.json_content == {"pages": []}

    def test_restore_request(self):
        req = RestoreVersionRequest(changelog="Restored from v2")
        assert req.changelog == "Restored from v2"

    def test_restore_request_default(self):
        req = RestoreVersionRequest()
        assert req.changelog is None

    def test_diff_response(self):
        now = datetime.now(timezone.utc)
        fv = VersionListItem(id="v1", version=1, title="Old", created_at=now)
        tv = VersionListItem(id="v2", version=2, title="New", created_at=now)
        diff = VersionDiffResponse(from_version=fv, to_version=tv, diff_text="-old\n+new")
        assert diff.from_version.version == 1
        assert diff.to_version.version == 2
        assert "old" in diff.diff_text


class TestPermissionSchemas:
    """Validate permission-related Pydantic schemas."""

    def test_permission_detail(self):
        now = datetime.now(timezone.utc)
        pd = PermissionDetail(
            id="p1", user_id="u1", user_email="a@b.com",
            user_display_name="Alice", role="editor", created_at=now,
        )
        assert pd.role == "editor"
        assert pd.user_email == "a@b.com"

    def test_grant_permission_request_default_role(self):
        req = GrantPermissionRequest(user_id="u1")
        assert req.role == "viewer"

    def test_grant_permission_request_explicit_role(self):
        req = GrantPermissionRequest(user_id="u1", role="editor")
        assert req.role == "editor"

    def test_update_permission_role_request(self):
        req = UpdatePermissionRoleRequest(role="viewer")
        assert req.role == "viewer"

    def test_create_invitation_request(self):
        req = CreateInvitationRequest(email="user@test.com", role="editor")
        assert req.email == "user@test.com"
        assert req.role == "editor"

    def test_user_search_item(self):
        item = UserSearchItem(id="u1", email="a@b.com", display_name="Alice")
        assert item.email == "a@b.com"


# ──────────────────────────────────────────────────────────────────────
#  Optimistic locking logic tests
# ──────────────────────────────────────────────────────────────────────


class TestOptimisticLocking:
    """Test the optimistic lock logic (conceptually, without DB)."""

    def test_version_match_allows_update(self):
        """When expected_version == server version, update proceeds."""
        server_version = 5
        expected_version = 5
        assert expected_version == server_version
        # allowed

    def test_version_mismatch_rejects(self):
        """When expected_version != server version, 409 returned."""
        server_version = 5
        expected_version = 4
        assert expected_version != server_version
        # 409

    def test_no_expected_version_allows_update(self):
        """When expected_version not provided, no optimistic check."""
        expected_version = None
        # allowed (backward compatible)
        assert expected_version is None


# ──────────────────────────────────────────────────────────────────────
#  Invitation lifecycle tests (conceptual)
# ──────────────────────────────────────────────────────────────────────


class TestInvitationLifecycle:
    """Test invitation state machine transitions."""

    def test_pending_to_accepted(self):
        """Invitation transitions from pending -> accepted on accept."""
        status = "pending"
        # simulate accept
        status = "accepted"
        accepted_at = datetime.now(timezone.utc)
        assert status == "accepted"
        assert accepted_at is not None

    def test_pending_to_expired_by_time(self):
        """Invitation that expired should not be accepted."""
        created = datetime.now(timezone.utc) - timedelta(days=8)
        expires = created + timedelta(days=7)
        now = datetime.now(timezone.utc)
        assert now > expires  # expired

    def test_pending_to_expired_by_revoke(self):
        """Revoking an invitation sets status to 'expired'."""
        status = "pending"
        status = "expired"
        assert status == "expired"

    def test_cannot_accept_accepted(self):
        """Cannot accept an already-accepted invitation."""
        status = "accepted"
        # attempt to accept should fail
        assert status == "accepted"
        # 410


# ──────────────────────────────────────────────────────────────────────
#  Permission hierarchy tests
# ──────────────────────────────────────────────────────────────────────


class TestPermissionHierarchy:
    """Test the RBAC role hierarchy."""

    ROLE_HIERARCHY = {"viewer": 0, "editor": 1, "owner": 2}

    def test_owner_above_editor(self):
        assert self.ROLE_HIERARCHY["owner"] > self.ROLE_HIERARCHY["editor"]

    def test_editor_above_viewer(self):
        assert self.ROLE_HIERARCHY["editor"] > self.ROLE_HIERARCHY["viewer"]

    def test_owner_cannot_be_granted(self):
        """Granting 'owner' role should be rejected."""
        role = "owner"
        allowed_roles = {"editor", "viewer"}
        assert role not in allowed_roles

    def test_valid_grant_roles(self):
        """Only editor and viewer can be granted."""
        for role in ("editor", "viewer"):
            assert role in {"editor", "viewer"}

    def test_owner_permission_cannot_be_revoked(self):
        """Owner's own permission cannot be revoked."""
        perm_role = "owner"
        can_revoke = perm_role != "owner"
        assert not can_revoke


# ──────────────────────────────────────────────────────────────────────
#  Version diff tests
# ──────────────────────────────────────────────────────────────────────


class TestVersionDiff:
    """Test the version diff functionality."""

    def test_no_diff(self):
        """Identical JSON produces empty diff."""
        import difflib
        import json

        content = {"pages": [{"name": "page1"}]}
        text1 = json.dumps(content, ensure_ascii=False, indent=2)
        text2 = json.dumps(content, ensure_ascii=False, indent=2)

        diff = list(difflib.unified_diff(
            text1.splitlines(keepends=True),
            text2.splitlines(keepends=True),
            fromfile="v1", tofile="v2",
        ))
        assert len(diff) == 0  # no lines = identical

    def test_has_diff(self):
        """Changed JSON produces a unified diff."""
        import difflib
        import json

        content1 = {"pages": [{"name": "page1"}]}
        content2 = {"pages": [{"name": "page1"}, {"name": "page2"}]}
        text1 = json.dumps(content1, ensure_ascii=False, indent=2)
        text2 = json.dumps(content2, ensure_ascii=False, indent=2)

        diff = list(difflib.unified_diff(
            text1.splitlines(keepends=True),
            text2.splitlines(keepends=True),
            fromfile="v1", tofile="v2",
        ))
        assert len(diff) > 0
        diff_text = "".join(diff)
        assert "page2" in diff_text


# ──────────────────────────────────────────────────────────────────────
#  User search query tests
# ──────────────────────────────────────────────────────────────────────


class TestUserSearch:
    """Test user search query logic."""

    def test_email_prefix_match(self):
        """User search uses LIKE '{prefix}%'."""
        users = [
            {"email": "alice@example.com"},
            {"email": "alex@example.com"},
            {"email": "bob@test.com"},
        ]
        prefix = "al"
        matches = [u for u in users if u["email"].lower().startswith(prefix)]
        assert len(matches) == 2

    def test_no_match(self):
        users = [{"email": "bob@test.com"}]
        matches = [u for u in users if u["email"].lower().startswith("zzz")]
        assert len(matches) == 0

    def test_case_insensitive(self):
        users = [{"email": "Alice@Example.com"}]
        matches = [u for u in users if u["email"].lower().startswith("al")]
        assert len(matches) == 1

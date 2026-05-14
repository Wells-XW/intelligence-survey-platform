"""Tests for sample distribution management (T12 — Phase 3).

Covers: sample groups, recipients, distributions, quotas, CSV import,
demographics matching, and the public token fill endpoint.
"""

from __future__ import annotations

import io
import json
import pytest
import pytest_asyncio
from httpx import AsyncClient


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


async def _create_survey(client: AsyncClient, headers: dict, title: str = "测试问卷") -> dict:
    """Create a survey and return its JSON."""
    resp = await client.post(
        "/api/v1/surveys",
        json={"title": title, "json_content": {"pages": []}},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


async def _publish_survey(client: AsyncClient, headers: dict, survey_id: str) -> None:
    """Publish a survey so distributions can be created."""
    resp = await client.put(
        f"/api/v1/surveys/{survey_id}",
        json={"status": "published"},
        headers=headers,
    )
    assert resp.status_code == 200


async def _create_sample_group(
    client: AsyncClient, headers: dict, survey_id: str, name: str = "测试样本组"
) -> dict:
    """Create a sample group and return its JSON."""
    resp = await client.post(
        f"/api/v1/surveys/{survey_id}/sample-groups",
        json={"name": name, "description": "测试描述"},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


async def _add_recipient(
    client: AsyncClient, headers: dict, survey_id: str, group_id: str,
    email: str = "test@example.com", name: str = "测试用户", demographics: dict | None = None
) -> dict:
    """Add a recipient and return JSON."""
    body = {"email": email, "name": name}
    if demographics:
        body["demographics"] = demographics
    resp = await client.post(
        f"/api/v1/surveys/{survey_id}/sample-groups/{group_id}/recipients",
        json=body,
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# Unit: CSV Parsing & Demographics Matching
# ═══════════════════════════════════════════════════════════════════════════


class TestCsvParsing:
    """Test the CSV recipient parser."""

    def test_basic_english_headers(self):
        """Parse CSV with English column headers."""
        from app.services.sample_service import parse_csv_recipients

        content = "email,name,age,city\nalice@test.com,Alice,25,NYC\nbob@test.com,Bob,30,LA"
        recipients, errors = parse_csv_recipients(content)

        assert len(recipients) == 2
        assert len(errors) == 0
        assert recipients[0]["email"] == "alice@test.com"
        assert recipients[0]["name"] == "Alice"
        assert recipients[0]["demographics"] == {"age": "25", "city": "NYC"}

    def test_chinese_headers(self):
        """Parse CSV with Chinese column headers."""
        from app.services.sample_service import parse_csv_recipients

        content = "邮箱,姓名,性别,年龄段\nzhang@test.com,张三,男,25-34"
        recipients, errors = parse_csv_recipients(content)

        assert len(recipients) == 1
        assert recipients[0]["email"] == "zhang@test.com"
        assert recipients[0]["name"] == "张三"
        assert recipients[0]["demographics"] == {"性别": "男", "年龄段": "25-34"}

    def test_missing_email_and_name(self):
        """Rows where both email and name are empty produce errors."""
        from app.services.sample_service import parse_csv_recipients

        content = "email,name,city\n,,北京\n,OnlyCity"
        recipients, errors = parse_csv_recipients(content)

        # Row 1: email empty, name empty (=北京 is in city column) — both email and name empty → error
        # Row 2: email empty, name="OnlyCity" — valid (name-only)
        assert len(recipients) == 1
        assert recipients[0]["name"] == "OnlyCity"
        assert len(errors) == 1

    def test_invalid_email_format(self):
        """Invalid email format produces errors."""
        from app.services.sample_service import parse_csv_recipients

        content = "email,name\nnot-an-email,User"
        recipients, errors = parse_csv_recipients(content)

        assert len(recipients) == 0
        assert len(errors) > 0
        assert "邮箱格式无效" in errors[0]

    def test_empty_csv(self):
        """Empty CSV returns empty result."""
        from app.services.sample_service import parse_csv_recipients

        recipients, errors = parse_csv_recipients("email,name\n")
        assert len(recipients) == 0

    def test_name_only_recipient(self):
        """Recipient with only name (no email) is valid."""
        from app.services.sample_service import parse_csv_recipients

        content = "name,city\n张三,北京"
        recipients, errors = parse_csv_recipients(content)

        assert len(recipients) == 1
        assert recipients[0]["name"] == "张三"
        assert recipients[0]["email"] is None

    def test_bom_handling(self):
        """BOM (byte order mark) in CSV is stripped."""
        from app.services.sample_service import parse_csv_recipients

        content = "﻿email,name\na@test.com,Alice"
        recipients, errors = parse_csv_recipients(content)

        assert len(recipients) == 1
        assert recipients[0]["email"] == "a@test.com"


class TestDemographicsMatch:
    """Test quota criteria matching logic."""

    def test_match_single_criterion(self):
        from app.services.sample_service import _demographics_match

        assert _demographics_match({"gender": "男"}, {"gender": "男"}) is True
        assert _demographics_match({"gender": "女"}, {"gender": "男"}) is False

    def test_match_multiple_criteria(self):
        from app.services.sample_service import _demographics_match

        assert _demographics_match(
            {"gender": "男", "age_group": "25-34", "education": "本科"},
            {"gender": "男", "age_group": "25-34"},
        ) is True

    def test_partial_match_fails(self):
        from app.services.sample_service import _demographics_match

        assert _demographics_match(
            {"gender": "男", "age_group": "25-34"},
            {"gender": "男", "education": "本科"},
        ) is False

    def test_empty_criteria(self):
        from app.services.sample_service import _demographics_match

        assert _demographics_match({"gender": "男"}, {}) is False

    def test_string_type_coercion(self):
        """String representation is used for comparison."""
        from app.services.sample_service import _demographics_match

        assert _demographics_match({"count": 5}, {"count": "5"}) is True
        assert _demographics_match({"count": 5}, {"count": "3"}) is False


# ═══════════════════════════════════════════════════════════════════════════
# API Integration: Sample Groups
# ═══════════════════════════════════════════════════════════════════════════


class TestSampleGroupAPI:
    """Test sample group CRUD via API."""

    @pytest.mark.asyncio
    async def test_create_and_list(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]

        # Create
        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/sample-groups",
            json={"name": "样本组A", "description": "第一组"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        group = resp.json()
        assert group["name"] == "样本组A"
        assert group["recipient_count"] == 0

        # List
        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/sample-groups",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        groups = resp.json()
        assert len(groups) == 1

    @pytest.mark.asyncio
    async def test_update_group(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        group = await _create_sample_group(async_client, auth_headers, sid)

        resp = await async_client.put(
            f"/api/v1/surveys/{sid}/sample-groups/{group['id']}",
            json={"name": "改名后的样本组"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "改名后的样本组"

    @pytest.mark.asyncio
    async def test_delete_group(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        group = await _create_sample_group(async_client, auth_headers, sid)

        resp = await async_client.delete(
            f"/api/v1/surveys/{sid}/sample-groups/{group['id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        # Verify deletion
        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/sample-groups",
            headers=auth_headers,
        )
        assert len(resp.json()) == 0


# ═══════════════════════════════════════════════════════════════════════════
# API Integration: Recipients
# ═══════════════════════════════════════════════════════════════════════════


class TestRecipientAPI:
    """Test recipient CRUD via API."""

    @pytest.mark.asyncio
    async def test_add_and_list(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        group = await _create_sample_group(async_client, auth_headers, sid)
        gid = group["id"]

        # Add
        recipient = await _add_recipient(
            async_client, auth_headers, sid, gid,
            email="a@b.com", name="Test",
            demographics={"gender": "男"},
        )
        assert recipient["status"] == "pending"
        assert recipient["demographics"]["gender"] == "男"
        assert len(recipient["unique_token"]) == 32

        # List (no unique_token in list)
        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/sample-groups/{gid}/recipients",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert "unique_token" not in items[0]  # Hidden in list view

        # Group count updated
        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/sample-groups/{gid}",
            headers=auth_headers,
        )
        assert resp.json()["recipient_count"] == 1

    @pytest.mark.asyncio
    async def test_update_demographics(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        group = await _create_sample_group(async_client, auth_headers, sid)
        gid = group["id"]
        recipient = await _add_recipient(async_client, auth_headers, sid, gid)

        resp = await async_client.put(
            f"/api/v1/surveys/{sid}/sample-groups/{gid}/recipients/{recipient['id']}",
            json={"demographics": {"age": "30", "city": "北京"}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["demographics"] == {"age": "30", "city": "北京"}

    @pytest.mark.asyncio
    async def test_delete_recipient(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        group = await _create_sample_group(async_client, auth_headers, sid)
        gid = group["id"]
        recipient = await _add_recipient(async_client, auth_headers, sid, gid)

        resp = await async_client.delete(
            f"/api/v1/surveys/{sid}/sample-groups/{gid}/recipients/{recipient['id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        # Count decremented
        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/sample-groups/{gid}",
            headers=auth_headers,
        )
        assert resp.json()["recipient_count"] == 0

    @pytest.mark.asyncio
    async def test_csv_import(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        group = await _create_sample_group(async_client, auth_headers, sid)
        gid = group["id"]

        csv_content = "email,name,gender,age_group\na@test.com,Alice,Female,18-24\nb@test.com,Bob,Male,25-34\n"
        files = {"file": ("recipients.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}

        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/sample-groups/{gid}/recipients/import",
            files=files,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["imported"] == 2

        # Verify count
        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/sample-groups/{gid}",
            headers=auth_headers,
        )
        assert resp.json()["recipient_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# API Integration: Distributions
# ═══════════════════════════════════════════════════════════════════════════


class TestDistributionAPI:
    """Test distribution lifecycle via API."""

    @pytest.mark.asyncio
    async def test_create_distribution(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        await _publish_survey(async_client, auth_headers, sid)
        group = await _create_sample_group(async_client, auth_headers, sid)

        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/distributions",
            json={
                "sample_group_id": group["id"],
                "name": "第一轮发放",
                "body_template": {"text": "您好，诚邀参与问卷调查", "link_label": "开始填写"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        dist = resp.json()
        assert dist["status"] == "draft"
        assert dist["name"] == "第一轮发放"

    @pytest.mark.asyncio
    async def test_distribution_requires_published(self, async_client, auth_headers):
        """Cannot create distribution on a draft survey."""
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        # Survey is still draft
        group = await _create_sample_group(async_client, auth_headers, sid)

        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/distributions",
            json={"sample_group_id": group["id"], "name": "Test"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_send_distribution(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        await _publish_survey(async_client, auth_headers, sid)
        group = await _create_sample_group(async_client, auth_headers, sid)
        gid = group["id"]

        # Add recipients
        await _add_recipient(async_client, auth_headers, sid, gid, email="a@b.com", name="A")
        await _add_recipient(async_client, auth_headers, sid, gid, email="c@d.com", name="B")

        # Create distribution
        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/distributions",
            json={"sample_group_id": gid, "name": "发送测试"},
            headers=auth_headers,
        )
        did = resp.json()["id"]

        # Send
        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/distributions/{did}/send",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["recipients_processed"] == 2
        assert result["links_generated"] == 2

        # Distribution status updated
        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/distributions/{did}",
            headers=auth_headers,
        )
        assert resp.json()["status"] == "sent"
        assert resp.json()["sent_count"] == 2

    @pytest.mark.asyncio
    async def test_list_distributions(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        await _publish_survey(async_client, auth_headers, sid)
        group = await _create_sample_group(async_client, auth_headers, sid)

        await async_client.post(
            f"/api/v1/surveys/{sid}/distributions",
            json={"sample_group_id": group["id"], "name": "D1"},
            headers=auth_headers,
        )
        await async_client.post(
            f"/api/v1/surveys/{sid}/distributions",
            json={"sample_group_id": group["id"], "name": "D2"},
            headers=auth_headers,
        )

        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/distributions",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ═══════════════════════════════════════════════════════════════════════════
# API Integration: Quotas
# ═══════════════════════════════════════════════════════════════════════════


class TestQuotaAPI:
    """Test quota CRUD via API."""

    @pytest.mark.asyncio
    async def test_create_and_list_quotas(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]

        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/quotas",
            json={
                "name": "男性配额",
                "dimension": "gender",
                "target_count": 50,
                "criteria": {"gender": "男"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        quota = resp.json()
        assert quota["fill_rate"] == 0.0
        assert quota["is_active"] is True

        # List
        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/quotas",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_update_quota(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]

        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/quotas",
            json={
                "name": "配额1",
                "dimension": "age_group",
                "target_count": 100,
                "criteria": {"age_group": "25-34"},
            },
            headers=auth_headers,
        )
        qid = resp.json()["id"]

        resp = await async_client.put(
            f"/api/v1/surveys/{sid}/quotas/{qid}",
            json={"target_count": 200, "is_active": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["target_count"] == 200
        assert resp.json()["is_active"] is False

    @pytest.mark.asyncio
    async def test_delete_quota(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]

        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/quotas",
            json={
                "name": "临时配额",
                "dimension": "education",
                "target_count": 10,
                "criteria": {"education": "本科"},
            },
            headers=auth_headers,
        )
        qid = resp.json()["id"]

        resp = await async_client.delete(
            f"/api/v1/surveys/{sid}/quotas/{qid}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_fill_rate_computed(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]

        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/quotas",
            json={
                "name": "测试配额",
                "dimension": "gender",
                "target_count": 100,
                "criteria": {"gender": "男"},
            },
            headers=auth_headers,
        )
        quota = resp.json()
        assert quota["fill_rate"] == 0.0
        assert quota["current_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# API Integration: Dashboard
# ═══════════════════════════════════════════════════════════════════════════


class TestDashboard:
    """Test the distribution dashboard aggregate endpoint."""

    @pytest.mark.asyncio
    async def test_dashboard_empty(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]

        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/distribution-dashboard",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_recipients"] == 0
        assert data["total_responded"] == 0
        assert data["response_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_dashboard_with_data(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers, title="仪表盘测试")
        sid = survey["id"]
        await _publish_survey(async_client, auth_headers, sid)
        group = await _create_sample_group(async_client, auth_headers, sid)
        gid = group["id"]

        # Add recipients
        await _add_recipient(async_client, auth_headers, sid, gid, email="a@b.com")
        await _add_recipient(async_client, auth_headers, sid, gid, email="c@d.com")

        # Create a quota
        await async_client.post(
            f"/api/v1/surveys/{sid}/quotas",
            json={
                "name": "测试配额",
                "dimension": "gender",
                "target_count": 50,
                "criteria": {"gender": "男"},
            },
            headers=auth_headers,
        )

        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/distribution-dashboard",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["survey_title"] == "仪表盘测试"
        assert data["total_recipients"] == 2
        assert len(data["sample_groups"]) == 1
        assert len(data["quotas"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# API Integration: Public Token Fill
# ═══════════════════════════════════════════════════════════════════════════


class TestPublicFill:
    """Test the public token-based fill endpoint."""

    @pytest.mark.asyncio
    async def test_resolve_valid_token(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        await _publish_survey(async_client, auth_headers, sid)
        group = await _create_sample_group(async_client, auth_headers, sid)
        gid = group["id"]

        # Add recipient and get token
        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/sample-groups/{gid}/recipients",
            json={"email": "respondent@test.com", "name": "受访者"},
            headers=auth_headers,
        )
        token = resp.json()["unique_token"]

        # Must send distribution first to mark as sent
        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/distributions",
            json={"sample_group_id": gid, "name": "发放"},
            headers=auth_headers,
        )
        did = resp.json()["id"]
        await async_client.post(
            f"/api/v1/surveys/{sid}/distributions/{did}/send",
            headers=auth_headers,
        )

        # Resolve token (public, no auth)
        resp = await async_client.get(f"/api/v1/surveys/fill/{token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["survey_id"] == sid
        assert data["token"] == token
        assert "redirect_url" in data

    @pytest.mark.asyncio
    async def test_invalid_token_404(self, async_client):
        resp = await async_client.get("/api/v1/surveys/fill/invalid_token_abcdef")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_token_for_unpublished_survey(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        # Don't publish — survey stays draft
        group = await _create_sample_group(async_client, auth_headers, sid)
        gid = group["id"]

        resp = await async_client.post(
            f"/api/v1/surveys/{sid}/sample-groups/{gid}/recipients",
            json={"email": "test@test.com", "name": "Test"},
            headers=auth_headers,
        )
        token = resp.json()["unique_token"]

        resp = await async_client.get(f"/api/v1/surveys/fill/{token}")
        assert resp.status_code == 404  # Can't fill unpublished survey


# ═══════════════════════════════════════════════════════════════════════════
# Permission Isolation
# ═══════════════════════════════════════════════════════════════════════════


class TestPermissionIsolation:
    """Test that users can't access other users' sample data."""

    @pytest.mark.asyncio
    async def test_other_user_cannot_access(self, async_client, auth_headers):
        """User B cannot see User A's sample groups."""
        survey = await _create_survey(async_client, auth_headers)
        sid = survey["id"]
        await _create_sample_group(async_client, auth_headers, sid)

        # Register a second user
        email2 = "other@example.com"
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": email2, "password": "Test1234!", "display_name": "Other"},
        )
        form = {"username": email2, "password": "Test1234!"}
        resp = await async_client.post("/api/v1/auth/login", data=form)
        tokens = resp.json()
        other_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        resp = await async_client.get(
            f"/api/v1/surveys/{sid}/sample-groups",
            headers=other_headers,
        )
        assert resp.status_code == 403  # No permission

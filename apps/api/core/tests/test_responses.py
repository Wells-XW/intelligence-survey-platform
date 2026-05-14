"""Tests for survey response collection and retrieval."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_submit_response_requires_published_survey(
    client: AsyncClient,
    auth_headers: dict,
):
    """Respondents can only submit to published surveys."""
    # Create a draft survey first
    resp = await client.post(
        "/api/v1/surveys",
        json={"title": "测试问卷", "json_content": {"pages": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    survey_id = resp.json()["id"]

    # Try submitting without publishing
    resp = await client.post(
        f"/api/v1/surveys/{survey_id}/responses",
        json={
            "answers": {"q1": "A"},
            "metadata": {"pipl_consent": True},
        },
    )
    assert resp.status_code == 403
    assert "未开放" in resp.json()["detail"]


@pytest.mark.anyio
async def test_submit_response_requires_pipl_consent(
    client: AsyncClient,
    auth_headers: dict,
):
    """Response submission must include PIPL consent."""
    # Create and publish a survey
    resp = await client.post(
        "/api/v1/surveys",
        json={"title": "公开问卷", "json_content": {"pages": []}},
        headers=auth_headers,
    )
    survey_id = resp.json()["id"]
    await client.put(
        f"/api/v1/surveys/{survey_id}",
        json={"status": "published"},
        headers=auth_headers,
    )

    # Submit without consent
    resp = await client.post(
        f"/api/v1/surveys/{survey_id}/responses",
        json={"answers": {}, "metadata": {}},
    )
    assert resp.status_code == 400
    assert "知情同意" in resp.json()["detail"]


@pytest.mark.anyio
async def test_submit_and_retrieve_response(
    client: AsyncClient,
    auth_headers: dict,
):
    """Full lifecycle: create survey → publish → submit response → retrieve."""
    # Create survey with questions
    resp = await client.post(
        "/api/v1/surveys",
        json={
            "title": "学术调查",
            "json_content": {
                "pages": [
                    {
                        "elements": [
                            {
                                "name": "q1",
                                "type": "radiogroup",
                                "title": "您的学历",
                                "choices": [
                                    {"value": "bachelor", "text": "本科"},
                                    {"value": "master", "text": "硕士"},
                                    {"value": "phd", "text": "博士"},
                                ],
                            }
                        ]
                    }
                ]
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    survey_id = resp.json()["id"]

    # Publish
    await client.put(
        f"/api/v1/surveys/{survey_id}",
        json={"status": "published"},
        headers=auth_headers,
    )

    # Submit responses (public, no auth)
    for answer in [{"q1": "bachelor"}, {"q1": "master"}, {"q1": "phd"}, {"q1": "phd"}]:
        r = await client.post(
            f"/api/v1/surveys/{survey_id}/responses",
            json={
                "answers": answer,
                "metadata": {"pipl_consent": True, "completion_time_seconds": 45.0},
            },
        )
        assert r.status_code == 201, r.text

    # Retrieve responses (auth required)
    r = await client.get(
        f"/api/v1/surveys/{survey_id}/responses", headers=auth_headers
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 4
    assert data[0]["completion_time_seconds"] == 45.0


@pytest.mark.anyio
async def test_list_responses_requires_auth(client: AsyncClient):
    """Listing responses without auth should fail."""
    resp = await client.get(
        "/api/v1/surveys/00000000-0000-0000-0000-000000000000/responses"
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_export_csv(
    client: AsyncClient,
    auth_headers: dict,
):
    """CSV export should return valid CSV with correct columns."""
    # Create + publish
    resp = await client.post(
        "/api/v1/surveys",
        json={"title": "导出测试", "json_content": {"pages": []}},
        headers=auth_headers,
    )
    survey_id = resp.json()["id"]
    await client.put(
        f"/api/v1/surveys/{survey_id}",
        json={"status": "published"},
        headers=auth_headers,
    )

    # Submit a response
    await client.post(
        f"/api/v1/surveys/{survey_id}/responses",
        json={
            "answers": {"q1": "A", "q2": 42},
            "metadata": {"pipl_consent": True},
        },
    )

    # Export
    r = await client.get(
        f"/api/v1/surveys/{survey_id}/responses/export?format=csv",
        headers=auth_headers,
    )
    assert r.status_code == 200
    content = r.text
    assert "response_id" in content
    assert "submitted_at" in content
    assert "q1" in content
    assert "q2" in content

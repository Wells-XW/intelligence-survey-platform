"""Integration tests for survey endpoints with auth."""

import pytest


async def _create_survey(client, headers, title="Test Survey"):
    resp = await client.post(
        "/api/v1/surveys",
        json={"title": title},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


async def _register_and_login(client, email, password="TestPass1", name="User"):
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    tokens = resp.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


class TestSurveyIsolation:
    async def test_list_only_own_surveys(self, async_client):
        headers_a = await _register_and_login(async_client, "a@test.com", "PassA123!")
        headers_b = await _register_and_login(async_client, "b@test.com", "PassB123!")

        # User A creates a survey
        await _create_survey(async_client, headers_a, "A's Survey")

        # User B creates a survey
        await _create_survey(async_client, headers_b, "B's Survey")

        # User A only sees A's survey
        resp_a = await async_client.get("/api/v1/surveys", headers=headers_a)
        surveys_a = resp_a.json()
        assert len(surveys_a) == 1
        assert surveys_a[0]["title"] == "A's Survey"

        # User B only sees B's survey
        resp_b = await async_client.get("/api/v1/surveys", headers=headers_b)
        surveys_b = resp_b.json()
        assert len(surveys_b) == 1
        assert surveys_b[0]["title"] == "B's Survey"

    async def test_cannot_access_others_survey(self, async_client):
        headers_a = await _register_and_login(async_client, "owner@test.com", "PassA123!")
        headers_b = await _register_and_login(async_client, "intruder@test.com", "PassB123!")

        survey = await _create_survey(async_client, headers_a, "Owner Survey")

        # User B tries to get User A's survey — should 404 (hides existence)
        resp = await async_client.get(
            f"/api/v1/surveys/{survey['id']}", headers=headers_b
        )
        assert resp.status_code == 404

    async def test_cannot_update_others_survey(self, async_client):
        headers_a = await _register_and_login(async_client, "editor-o@test.com", "PassA123!")
        headers_b = await _register_and_login(async_client, "editor-i@test.com", "PassB123!")

        survey = await _create_survey(async_client, headers_a)

        resp = await async_client.put(
            f"/api/v1/surveys/{survey['id']}",
            json={"title": "Hacked!"},
            headers=headers_b,
        )
        assert resp.status_code == 404

    async def test_cannot_delete_others_survey(self, async_client):
        headers_a = await _register_and_login(async_client, "del-o@test.com", "PassA123!")
        headers_b = await _register_and_login(async_client, "del-i@test.com", "PassB123!")

        survey = await _create_survey(async_client, headers_a)

        resp = await async_client.delete(
            f"/api/v1/surveys/{survey['id']}", headers=headers_b
        )
        assert resp.status_code == 404


class TestSurveyAuth:
    async def test_owner_can_delete(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        resp = await async_client.delete(
            f"/api/v1/surveys/{survey['id']}", headers=auth_headers
        )
        assert resp.status_code == 204

    async def test_survey_has_owner_id(self, async_client, auth_headers):
        survey = await _create_survey(async_client, auth_headers)
        assert survey["owner_id"] is not None

    async def test_unauthenticated_rejected(self, async_client):
        # List
        resp = await async_client.get("/api/v1/surveys")
        assert resp.status_code == 401

        # Create
        resp = await async_client.post(
            "/api/v1/surveys", json={"title": "X"}
        )
        assert resp.status_code == 401

        # Get
        resp = await async_client.get(
            "/api/v1/surveys/550e8400-e29b-41d4-a716-446655440000"
        )
        assert resp.status_code == 401

        # Update
        resp = await async_client.put(
            "/api/v1/surveys/550e8400-e29b-41d4-a716-446655440000",
            json={"title": "X"},
        )
        assert resp.status_code == 401

        # Delete
        resp = await async_client.delete(
            "/api/v1/surveys/550e8400-e29b-41d4-a716-446655440000"
        )
        assert resp.status_code == 401

    async def test_survey_crud_with_auth(self, async_client, auth_headers):
        # Create
        s = await _create_survey(async_client, auth_headers, "My Survey")
        assert s["title"] == "My Survey"
        sid = s["id"]

        # Read
        resp = await async_client.get(f"/api/v1/surveys/{sid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "My Survey"

        # Update
        resp = await async_client.put(
            f"/api/v1/surveys/{sid}",
            json={"title": "Updated"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"
        assert resp.json()["version"] == 2

        # Delete
        resp = await async_client.delete(f"/api/v1/surveys/{sid}", headers=auth_headers)
        assert resp.status_code == 204


class TestRateLimit:
    async def test_rate_limit_triggers(self, async_client):
        """Send rapid requests to trigger the 429 limit."""
        # Send 65 requests rapidly; expect at least one 429
        statuses = []
        for _ in range(65):
            resp = await async_client.get("/api/v1/health")
            statuses.append(resp.status_code)
        assert 429 in statuses

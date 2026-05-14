"""Integration tests for auth endpoints."""

import pytest


class TestRegister:
    async def test_register_success(self, async_client):
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={
                "email": "new@example.com",
                "password": "TestPass1",
                "display_name": "New User",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "new@example.com"
        assert data["display_name"] == "New User"
        assert data["is_active"] is True
        assert "id" in data
        assert "hashed_password" not in data

    async def test_register_duplicate_email(self, async_client):
        body = {"email": "dup@example.com", "password": "TestPass1", "display_name": "X"}
        resp1 = await async_client.post("/api/v1/auth/register", json=body)
        assert resp1.status_code == 201

        resp2 = await async_client.post("/api/v1/auth/register", json=body)
        assert resp2.status_code == 409
        assert "已被注册" in resp2.json()["detail"]

    async def test_register_weak_password(self, async_client):
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "x@x.com", "password": "short", "display_name": "X"},
        )
        # Pydantic raises 422 for model validation errors from model_validator
        # that raises ValueError — FastAPI converts to 422 with detail from ValueError
        assert resp.status_code == 422


class TestLogin:
    @pytest.fixture
    async def registered_user(self, async_client):
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "login@test.com", "password": "TestPass1", "display_name": "Tester"},
        )

    async def test_login_success(self, async_client, registered_user):
        resp = await async_client.post(
            "/api/v1/auth/login",
            data={"username": "login@test.com", "password": "TestPass1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    async def test_login_wrong_password(self, async_client, registered_user):
        resp = await async_client.post(
            "/api/v1/auth/login",
            data={"username": "login@test.com", "password": "WrongPass1"},
        )
        assert resp.status_code == 401
        assert "错误" in resp.json()["detail"]

    async def test_login_nonexistent(self, async_client):
        resp = await async_client.post(
            "/api/v1/auth/login",
            data={"username": "no@user.com", "password": "TestPass1"},
        )
        assert resp.status_code == 401


class TestRefresh:
    async def test_refresh_success(self, async_client):
        # Register + login
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "rf@test.com", "password": "TestPass1", "display_name": "X"},
        )
        login = await async_client.post(
            "/api/v1/auth/login",
            data={"username": "rf@test.com", "password": "TestPass1"},
        )
        refresh_token = login.json()["refresh_token"]

        # Refresh
        resp = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200
        new_tokens = resp.json()
        assert new_tokens["access_token"] != login.json()["access_token"]
        assert new_tokens["refresh_token"] != refresh_token

    async def test_refresh_reuse_detected(self, async_client):
        # Register + login
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "rf2@test.com", "password": "TestPass1", "display_name": "X"},
        )
        login = await async_client.post(
            "/api/v1/auth/login",
            data={"username": "rf2@test.com", "password": "TestPass1"},
        )
        rt = login.json()["refresh_token"]

        # First refresh — OK
        r1 = await async_client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
        assert r1.status_code == 200

        # Second refresh with same token — should detect reuse
        r2 = await async_client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
        assert r2.status_code == 401

    async def test_refresh_invalid_token(self, async_client):
        resp = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "not.a.valid.token"},
        )
        assert resp.status_code == 401


class TestMe:
    async def test_get_me_authenticated(self, async_client, auth_headers):
        resp = await async_client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert data["display_name"] == "Test User"

    async def test_get_me_unauthenticated(self, async_client):
        resp = await async_client.get("/api/v1/auth/me")
        assert resp.status_code == 401

"""Task 18.3 — Dual-auth wiring integration test.

Validates that the unified principal resolver in ``app.core.deps`` accepts
both Bearer JWT tokens and API key plaintexts (via either ``X-API-Key`` or
``Authorization: Bearer sk_…``), gives JWT precedence when both are
presented, and rejects revoked or expired API keys with the documented
machine codes.

Validates: Requirements 8.1, 8.2, 8.3
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import pytest

from app.core.api_key_secret import generate_plaintext
from app.core.security import create_access_token, hash_password
from app.models.api_key import ApiKey
from app.models.user import User


async def _make_user(db_session, *, email: str, display_name: str = "Tester") -> User:
    """Insert a User row and flush so the API handler can read it back.

    Writes use ``flush`` rather than ``commit`` because the conftest
    ``db_session`` fixture wraps the test in an outer transaction that
    rolls back at teardown. Flushed rows are visible to the FastAPI
    handler (which shares the same session via dependency override) but
    are reverted cleanly when the test ends.
    """
    user = User(
        email=email,
        hashed_password=hash_password("Test1234!"),
        display_name=display_name,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_api_key(
    db_session,
    *,
    user: User,
    name: str = "test-key",
    scopes: Optional[List[str]] = None,
    revoked_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
    env: str = "live",
) -> Tuple[str, ApiKey]:
    """Create an API key row and return its plaintext + ORM row."""
    plaintext, key_prefix, key_hash = generate_plaintext(env)
    row = ApiKey(
        user_id=user.id,
        name=name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=scopes if scopes is not None else ["survey:read"],
        revoked_at=revoked_at,
        expires_at=expires_at,
    )
    db_session.add(row)
    await db_session.flush()
    return plaintext, row


@pytest.mark.asyncio
async def test_jwt_only_path_authenticates(async_client, db_session):
    """JWT bearer token alone resolves to the token's subject user."""
    user = await _make_user(db_session, email="jwt-only@example.com")
    token = create_access_token(user.id)

    r = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "jwt-only@example.com"


@pytest.mark.asyncio
async def test_api_key_path_authenticates_with_x_api_key_header(
    async_client, db_session
):
    """API key plaintext sent via ``X-API-Key`` resolves to the key's owner."""
    user = await _make_user(db_session, email="apikey-header@example.com")
    plaintext, _ = await _make_api_key(db_session, user=user)

    r = await async_client.get(
        "/api/v1/auth/me",
        headers={"X-API-Key": plaintext},
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "apikey-header@example.com"


@pytest.mark.asyncio
async def test_api_key_path_authenticates_with_authorization_bearer(
    async_client, db_session
):
    """API key plaintext routed through ``Authorization: Bearer`` is accepted.

    The resolver tries the value as a JWT first; when JWT decode fails
    and the bearer literal starts with ``sk_``, it falls through to the
    API key path.
    """
    user = await _make_user(db_session, email="apikey-bearer@example.com")
    plaintext, _ = await _make_api_key(db_session, user=user)

    r = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "apikey-bearer@example.com"


@pytest.mark.asyncio
async def test_jwt_wins_when_both_presented(async_client, db_session):
    """When a JWT and an API key are both present, the JWT principal wins."""
    jwt_user = await _make_user(db_session, email="jwt-winner@example.com")
    key_user = await _make_user(db_session, email="key-loser@example.com")
    token = create_access_token(jwt_user.id)
    plaintext, _ = await _make_api_key(db_session, user=key_user)

    r = await async_client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-API-Key": plaintext,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == jwt_user.id
    assert body["email"] == "jwt-winner@example.com"


@pytest.mark.asyncio
async def test_no_credentials_returns_401(async_client):
    """A bare request with no credentials is rejected with 401."""
    r = await async_client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_revoked_api_key_returns_401(async_client, db_session):
    """A revoked API key is rejected with the ``api_key_revoked`` error."""
    user = await _make_user(db_session, email="revoked@example.com")
    plaintext, _ = await _make_api_key(
        db_session,
        user=user,
        revoked_at=datetime.now(timezone.utc),
    )

    r = await async_client.get(
        "/api/v1/auth/me",
        headers={"X-API-Key": plaintext},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["detail"]["error"] == "api_key_revoked"


@pytest.mark.asyncio
async def test_expired_api_key_returns_401(async_client, db_session):
    """An expired API key is rejected with the ``api_key_expired`` error."""
    user = await _make_user(db_session, email="expired@example.com")
    plaintext, _ = await _make_api_key(
        db_session,
        user=user,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    r = await async_client.get(
        "/api/v1/auth/me",
        headers={"X-API-Key": plaintext},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["detail"]["error"] == "api_key_expired"

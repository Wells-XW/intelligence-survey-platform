"""FastAPI dependencies for authentication and authorization.

This module composes the platform's two authentication paths — JWT bearer
tokens for interactive UI users and long-lived API keys for machine
integrators — into a single :class:`Principal` value that downstream
routes can depend on uniformly.

Resolution order, fixed by design §Auth resolution flow:

1. ``Authorization: Bearer <token>`` is tried as a JWT first.
2. If JWT decoding fails and the same bearer value starts with ``sk_``,
   it is treated as an API key plaintext.
3. Otherwise the ``X-API-Key`` header is consulted as a fallback API key.
4. If none of the above resolves a valid identity, a 401 is raised.

JWT principals receive the wildcard scope ``"*"`` (their RBAC role gates
them at the survey level). API key principals receive exactly the scopes
stored on the key row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import FrozenSet, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models.api_key import ApiKey
from ..models.survey_permission import SurveyPermission
from ..models.user import User
from .api_key_secret import verify as verify_api_key_secret
from .security import decode_token

# OAuth2 scheme: extracts Bearer token from Authorization header
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)

# Role hierarchy — higher value = more permissions
ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "editor": 1,
    "owner": 2,
}


@dataclass(frozen=True)
class Principal:
    """Authenticated identity composed from JWT or API key.

    The dataclass is frozen so it can be passed safely through FastAPI's
    dependency graph without callers being able to mutate the resolved
    identity mid-request.

    Attributes:
        user: The platform user associated with this request. For JWT
            principals this is the token's subject; for API key
            principals it is the key's owning user.
        api_key: The :class:`ApiKey` row that authenticated the request,
            or ``None`` when authentication came from a JWT.
        scopes: The set of scope labels granted to this principal. JWT
            principals carry the singleton ``{"*"}`` (their RBAC role
            already gates per-survey access). API key principals carry
            exactly the scopes persisted on the key row.
    """

    user: User
    api_key: Optional[ApiKey]
    scopes: FrozenSet[str]


def _auth_error(error_code: str) -> HTTPException:
    """Build a structured 401 response with a stable machine code.

    Args:
        error_code: Stable identifier consumed by API clients (for
            example ``"api_key_revoked"``).

    Returns:
        An :class:`HTTPException` with status 401 and a dict body of the
        form ``{"error": <error_code>}``, plus the standard
        ``WWW-Authenticate`` header.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": error_code},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _resolve_jwt_principal(
    token: str, db: AsyncSession
) -> Optional[Principal]:
    """Try to resolve a bearer token as a JWT and build a Principal.

    Args:
        token: The raw bearer token string (without the ``Bearer`` prefix).
        db: Active async database session.

    Returns:
        A :class:`Principal` when the token is a valid JWT access token
        whose subject maps to an active user. ``None`` when the token
        cannot be decoded as a JWT (caller may fall through to the API
        key path).

    Raises:
        HTTPException: When the token is a valid JWT but is the wrong
            type, has no subject, references an unknown user, or
            references a disabled user.
    """
    try:
        payload = decode_token(token)
    except Exception:
        return None

    if payload.get("type") != "access":
        raise _auth_error("auth_required")

    user_id = payload.get("sub")
    if not user_id:
        raise _auth_error("auth_required")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise _auth_error("auth_required")

    return Principal(user=user, api_key=None, scopes=frozenset({"*"}))


async def _resolve_api_key_principal(
    plaintext: str, db: AsyncSession
) -> Principal:
    """Validate an API key plaintext and build a Principal.

    Args:
        plaintext: The presented secret in the form
            ``sk_<env>_<24 url-safe chars>``.
        db: Active async database session.

    Returns:
        A :class:`Principal` carrying the resolved owner user, the
        :class:`ApiKey` row, and the key's stored scopes.

    Raises:
        HTTPException: 401 with a stable machine code when the key is
            unknown (``api_key_invalid``), the hash does not match
            (``api_key_invalid``), the key has been revoked
            (``api_key_revoked``), the key has expired
            (``api_key_expired``), or the owning user is disabled
            (``owner_disabled``).
    """
    key_prefix = plaintext[:11]

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_prefix == key_prefix)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise _auth_error("api_key_invalid")

    if not verify_api_key_secret(plaintext, row.key_hash):
        raise _auth_error("api_key_invalid")

    if row.revoked_at is not None:
        raise _auth_error("api_key_revoked")

    now = datetime.now(timezone.utc)
    if row.expires_at is not None and row.expires_at <= now:
        raise _auth_error("api_key_expired")

    owner_result = await db.execute(select(User).where(User.id == row.user_id))
    owner = owner_result.scalar_one_or_none()
    if owner is None or not owner.is_active:
        raise _auth_error("owner_disabled")

    # Best-effort last_used_at stamping. Failure here must never break
    # an otherwise valid request, so we swallow any exception.
    try:
        await db.execute(
            update(ApiKey).where(ApiKey.id == row.id).values(last_used_at=now)
        )
        await db.flush()
    except Exception:
        pass

    return Principal(
        user=owner,
        api_key=row,
        scopes=frozenset(row.scopes or []),
    )


async def get_principal(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Principal:
    """Resolve the authenticated :class:`Principal` for the request.

    Resolution order, per design §Auth resolution flow:

    1. ``Authorization: Bearer <token>`` is tried as a JWT first. A
       valid access token whose subject is an active user produces a
       JWT principal with wildcard scopes.
    2. If JWT decoding raises, and the same bearer value starts with
       ``sk_``, it is treated as an API key plaintext.
    3. Otherwise the ``X-API-Key`` header is consulted for an API key
       plaintext.
    4. When neither path yields a valid identity, a 401 with machine
       code ``auth_required`` is raised.

    Args:
        request: The incoming FastAPI request, used to read raw
            ``Authorization`` and ``X-API-Key`` headers without going
            through :data:`oauth2_scheme` (which strips the API-key
            fallback).
        db: Active async database session.

    Returns:
        The resolved :class:`Principal`.

    Raises:
        HTTPException: 401 with one of the machine codes
            ``auth_required``, ``api_key_invalid``, ``api_key_revoked``,
            ``api_key_expired``, or ``owner_disabled`` per the cases
            described above.
    """
    api_key_candidate: Optional[str] = None

    authorization = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    )
    if authorization:
        scheme, _, token = authorization.partition(" ")
        token = token.strip()
        if scheme.lower() == "bearer" and token:
            principal = await _resolve_jwt_principal(token, db)
            if principal is not None:
                return principal
            # JWT decoding failed; the same bearer value may itself be
            # an API key plaintext that the client routed through the
            # Authorization header.
            if token.startswith("sk_"):
                api_key_candidate = token

    if api_key_candidate is None:
        header_key = request.headers.get("X-API-Key") or request.headers.get(
            "x-api-key"
        )
        if header_key and header_key.startswith("sk_"):
            api_key_candidate = header_key

    if api_key_candidate is None:
        raise _auth_error("auth_required")

    return await _resolve_api_key_principal(api_key_candidate, db)


async def get_current_user(
    principal: Principal = Depends(get_principal),
) -> User:
    """Return the authenticated :class:`User` behind the request.

    This is a thin wrapper over :func:`get_principal` so that every
    existing router that depends on ``get_current_user`` transparently
    accepts both JWT and API key callers without per-route changes.

    Args:
        principal: The resolved principal injected by FastAPI.

    Returns:
        The user attached to ``principal``.
    """
    return principal.user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Resolve the authenticated user, or ``None`` when none is present.

    Used by endpoints that behave differently for authenticated versus
    anonymous callers. Any authentication failure (missing credentials,
    invalid token, revoked or expired API key, disabled owner) is
    collapsed to ``None`` so callers do not need to distinguish between
    "no credentials" and "bad credentials".

    Args:
        request: The incoming FastAPI request.
        db: Active async database session.

    Returns:
        The resolved :class:`User` or ``None``.
    """
    try:
        principal = await get_principal(request=request, db=db)
    except HTTPException:
        return None
    return principal.user


def require_scope(label: str):
    """Build a dependency that enforces a single API-key scope label.

    JWT-authenticated principals always pass: their RBAC role on the
    target resource (checked separately via
    :func:`check_survey_permission`) is what gates them. API-key
    principals must carry ``label`` in their stored scopes — the
    wildcard ``"*"`` is also honoured for symmetry with JWT principals.

    Args:
        label: The scope string to require, for example
            ``"survey:read"`` or ``"export:write"``.

    Returns:
        An async FastAPI dependency that returns the resolved
        :class:`Principal` on success and raises 403 with machine code
        ``insufficient_scope`` otherwise.
    """

    async def _require_scope_dep(
        principal: Principal = Depends(get_principal),
    ) -> Principal:
        if "*" in principal.scopes:
            return principal
        if label not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_scope",
                    "required_scope": label,
                },
            )
        return principal

    return _require_scope_dep


def _check_role(perm: SurveyPermission, min_role: str) -> None:
    """Raise 403 if the permission's role is below *min_role*."""
    user_level = ROLE_HIERARCHY.get(perm.role, -1)
    required = ROLE_HIERARCHY.get(min_role, 99)
    if user_level < required:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足",
        )


async def check_survey_permission(
    survey_id: str,
    user: User,
    min_role: str,
    db: AsyncSession,
) -> SurveyPermission:
    """Verify the user has at least *min_role* on the survey.

    Returns the ``SurveyPermission`` row on success.

    Raises 404 if no permission exists (hides survey existence from
    unauthorized users).
    Raises 403 if the role is insufficient.
    """
    result = await db.execute(
        select(SurveyPermission).where(
            SurveyPermission.survey_id == survey_id,
            SurveyPermission.user_id == user.id,
        )
    )
    perm = result.scalar_one_or_none()

    if perm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="问卷不存在",
        )

    _check_role(perm, min_role)
    return perm


# ── Optional infrastructure dependencies ──────────────────────────────────

from typing import Optional as _Optional

import redis.asyncio as aioredis  # noqa: E402


async def get_redis() -> _Optional[aioredis.Redis]:
    """Yield an async Redis client, or ``None`` if Redis is unavailable.

    Used for caching literature search results and other ephemeral data.
    Gracefully degrades: callers should treat ``None`` as "cache miss"
    rather than an error.
    """
    try:
        client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await client.ping()
    except (aioredis.ConnectionError, OSError):
        yield None
    else:
        try:
            yield client
        finally:
            await client.close()

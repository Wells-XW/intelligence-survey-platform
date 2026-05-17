"""API key lifecycle routes for the platform's machine-credential surface.

These endpoints implement Component 2 of the design: ``POST /``,
``GET /``, ``POST /{key_id}/rotate``, ``POST /{key_id}/revoke``, and
``DELETE /{key_id}``. They satisfy Requirements 2.1, 2.4, 2.5, 2.8, and
2.9.

Per Req 8 AC5 the API platform must never issue, refresh, or extend
caller credentials through an API-key-authenticated path. Every route
in this module therefore depends on :func:`_require_jwt_principal`,
which rejects principals whose ``api_key`` attribute is non-null with a
403 ``jwt_only`` error, no matter how broad the presented key's scopes
are. JWT-authenticated callers continue through unchanged.

The plaintext secret is returned to the client exactly once — at
creation and at rotation — and is never persisted; ``key_prefix`` and
``key_hash`` are stored in their place. List, revoke, and delete
responses never carry plaintext.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.api_key_secret import generate_plaintext
from ...core.audit import log_audit
from ...core.deps import Principal, get_principal
from ...database import get_db
from ...models.api_key import ApiKey
from ...schemas.api_key import (
    ApiKeyCreateIn,
    ApiKeyCreateOut,
    ApiKeyOut,
    ApiKeyRotateOut,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


# ── Module constants ──────────────────────────────────────────────────

#: Fixed scope enumeration drawn from design §Component 2. Any scope
#: string outside this set is rejected with a 400 ``scope_invalid``
#: response. The two admin-only entries (``admin:*`` family and
#: ``audit:read``) additionally require ``User.is_admin`` on the caller
#: per design §Component 2.
SCOPE_ENUM: frozenset[str] = frozenset(
    {
        "survey:read",
        "survey:write",
        "response:read",
        "response:write",
        "export:read",
        "export:write",
        "webhook:manage",
        "admin:read",
        "admin:write",
        "audit:read",
    }
)

#: Default plaintext environment tag. Keys minted by this router are
#: live keys; the ``test`` namespace is reserved for future sandbox
#: integration. Held as a module constant rather than a setting so the
#: invariant is visible in code review.
_PLAINTEXT_ENV: str = "live"

#: Hard-delete retention floor used by :func:`_can_hard_delete`. The
#: project does not yet expose a per-feature audit retention setting,
#: so we use 30 days as a conservative proxy that matches the audit
#: retention guarantees referenced by the spec. Replace with the global
#: audit retention setting once that lands.
_HARD_DELETE_RETENTION: timedelta = timedelta(days=30)


# ── Auth and validation helpers ───────────────────────────────────────


def _require_jwt_principal(
    principal: Principal = Depends(get_principal),
) -> Principal:
    """Reject API-key callers from API-key management endpoints.

    Implements Req 8 AC5: API keys must never grant the ability to
    manage other keys. Callers authenticated via JWT pass through
    unchanged; callers authenticated via API key receive a 403 with
    machine code ``jwt_only``.

    Args:
        principal: The resolved request principal.

    Returns:
        The principal when JWT-authenticated.

    Raises:
        HTTPException: 403 ``jwt_only`` when the principal carries a
            non-null ``api_key`` attribute.
    """
    if principal.api_key is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "jwt_only"},
        )
    return principal


def _validate_scopes(scopes: List[str], is_admin: bool) -> None:
    """Validate a candidate scope list against the canonical enum.

    Two failure modes are surfaced separately so the client can
    distinguish a typo from an authorization gap:

    * Unknown scope strings yield 400 ``scope_invalid`` with the
      offending entries echoed back.
    * Admin-only scopes (``admin:*`` or ``audit:read``) requested by a
      non-admin caller yield 403 ``admin_scope_requires_is_admin``.

    Args:
        scopes: The non-empty scope list submitted by the caller.
        is_admin: Whether the caller's :class:`User.is_admin` flag is
            set.

    Raises:
        HTTPException: 400 when ``scopes`` is empty or contains
            unknown entries, 403 when admin-only scopes are requested
            without ``is_admin``.
    """
    if not scopes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "scopes_required"},
        )

    unknown = [s for s in scopes if s not in SCOPE_ENUM]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "scope_invalid", "unknown_scopes": unknown},
        )

    requires_admin = [
        s for s in scopes if s.startswith("admin:") or s == "audit:read"
    ]
    if requires_admin and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "admin_scope_requires_is_admin",
                "scopes": requires_admin,
            },
        )


def _validate_expires_at(expires_at: Optional[datetime]) -> Optional[datetime]:
    """Validate the optional ``expires_at`` payload field.

    The platform stores expiration timestamps in
    ``DateTime(timezone=True)`` columns; passing a naive datetime would
    silently coerce to a server-local interpretation in some SQLAlchemy
    versions. We reject naive timestamps explicitly and require the
    expiry to be strictly in the future at submission time.

    Args:
        expires_at: The submitted expiration, or ``None``.

    Returns:
        The unchanged ``expires_at`` value when valid, or ``None``.

    Raises:
        HTTPException: 400 ``expires_at_naive`` when timezone-naive,
            400 ``expires_at_in_past`` when at or before ``now``.
    """
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "expires_at_naive"},
        )
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "expires_at_in_past"},
        )
    return expires_at


def _is_inactive(row: ApiKey, now: datetime, threshold: timedelta) -> bool:
    """Compute the per-row inactive flag for the list response.

    A key is "inactive" when it has not been used for at least
    :attr:`Settings.api_key_inactivity_threshold_days`. When the key
    has never been used, ``created_at`` stands in for ``last_used_at``
    so a freshly created key is not flagged spuriously.

    Args:
        row: The :class:`ApiKey` ORM row under inspection.
        now: The current UTC timestamp; passed in so a single call to
            :func:`datetime.now` is shared across the list response.
        threshold: The inactivity threshold from settings.

    Returns:
        ``True`` if the key qualifies as inactive, ``False`` otherwise.
    """
    last_seen = row.last_used_at or row.created_at
    return (now - last_seen) >= threshold


def _can_hard_delete(row: ApiKey, now: datetime) -> Tuple[bool, str]:
    """Gate hard-delete on revocation status and audit retention.

    A key may be hard-deleted only when it has already been revoked
    *and* the audit retention period has elapsed since revocation. The
    blocked path returns a stable machine code so the client can
    distinguish "revoke first" from "wait longer".

    Args:
        row: The :class:`ApiKey` row targeted for deletion.
        now: The current UTC timestamp.

    Returns:
        A ``(allowed, reason)`` pair. ``reason`` is ``""`` on the
        allowed path, otherwise ``"not_revoked"`` or
        ``"retention_pending"``.
    """
    if row.revoked_at is None:
        return False, "not_revoked"
    if (now - row.revoked_at) < _HARD_DELETE_RETENTION:
        return False, "retention_pending"
    return True, ""


def _build_out_payload(row: ApiKey, now: datetime, threshold: timedelta) -> dict:
    """Serialize an :class:`ApiKey` row into the shared output shape.

    The shape matches both :class:`ApiKeyOut` (no ``plaintext``) and
    the metadata portion of :class:`ApiKeyCreateOut` /
    :class:`ApiKeyRotateOut`; callers that need plaintext attach it
    after calling this helper.

    Args:
        row: The :class:`ApiKey` row.
        now: The current UTC timestamp, used to compute ``inactive``.
        threshold: The inactivity threshold.

    Returns:
        A dict suitable for ``ApiKeyOut(**payload)`` or, with a
        ``plaintext`` entry merged in, ``ApiKeyCreateOut(**payload)``.
    """
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "scopes": list(row.scopes or []),
        "rate_limit_overrides": row.rate_limit_overrides,
        "expires_at": row.expires_at,
        "last_used_at": row.last_used_at,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "inactive": _is_inactive(row, now, threshold),
    }


# ── Routes ────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=ApiKeyCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
    description=(
        "Issue a new long-lived API key bound to the authenticated "
        "user. The plaintext secret is returned in the response body "
        "exactly once — capture it now, it cannot be recovered later. "
        "Only ``key_prefix`` and ``key_hash`` are persisted."
    ),
)
async def create_api_key(
    body: ApiKeyCreateIn,
    request: Request,
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateOut:
    """Create a new API key for the authenticated user.

    Generates a fresh plaintext via
    :func:`app.core.api_key_secret.generate_plaintext`, stores only
    ``key_prefix`` and ``key_hash``, and returns the plaintext to the
    caller exactly once. Emits an ``api_key.create`` audit row whose
    ``details`` carry the new key id, owner-supplied name, and
    granted scopes.

    Args:
        body: New-key payload with ``name``, ``scopes``, optional
            ``expires_at``, and optional ``rate_limit_overrides``.
        request: Inbound request, used for audit attribution.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        The :class:`ApiKeyCreateOut` payload, with plaintext set.

    Raises:
        HTTPException: 400 / 403 on scope or expiry validation
            failures (see :func:`_validate_scopes` and
            :func:`_validate_expires_at`).
    """
    _validate_scopes(list(body.scopes), principal.user.is_admin)
    expires_at = _validate_expires_at(body.expires_at)

    plaintext, key_prefix, key_hash = generate_plaintext(_PLAINTEXT_ENV)

    row = ApiKey(
        user_id=principal.user.id,
        name=body.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=list(body.scopes),
        rate_limit_overrides=body.rate_limit_overrides,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()

    await log_audit(
        db,
        action="api_key.create",
        user_id=principal.user.id,
        resource_type="api_key",
        resource_id=row.id,
        details={"key_id": row.id, "name": row.name, "scopes": list(row.scopes)},
        request=request,
    )

    await db.commit()
    await db.refresh(row)

    now = datetime.now(timezone.utc)
    threshold = timedelta(days=settings.api_key_inactivity_threshold_days)
    payload = _build_out_payload(row, now, threshold)
    payload["plaintext"] = plaintext
    return ApiKeyCreateOut(**payload)


@router.get(
    "/",
    response_model=List[ApiKeyOut],
    summary="List the caller's API keys",
    description=(
        "Return every API key owned by the authenticated user — "
        "active, revoked, and expired — in newest-first order. "
        "Plaintext and hash fields are never included."
    ),
)
async def list_api_keys(
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> List[ApiKeyOut]:
    """List the authenticated user's API keys.

    Returns every key the caller owns — active, revoked, and expired —
    so the user has a single place to review credential history.
    Plaintext and hash fields are never included; the per-row
    ``inactive`` flag is computed from ``last_used_at`` (or
    ``created_at`` when the key has never been used) against the
    configured inactivity threshold per Req 2.9.

    Args:
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        A list of :class:`ApiKeyOut` payloads in newest-first order.
    """
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == principal.user.id)
        .order_by(ApiKey.created_at.desc())
    )
    rows = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    threshold = timedelta(days=settings.api_key_inactivity_threshold_days)
    return [ApiKeyOut(**_build_out_payload(row, now, threshold)) for row in rows]


@router.post(
    "/{key_id}/rotate",
    response_model=ApiKeyRotateOut,
    summary="Rotate an API key's secret",
    description=(
        "Generate a fresh plaintext secret for an existing key, "
        "replacing ``key_prefix`` and ``key_hash`` in place. The new "
        "plaintext is returned exactly once. The previous secret is "
        "invalidated immediately upon rotation."
    ),
)
async def rotate_api_key(
    key_id: str,
    request: Request,
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyRotateOut:
    """Rotate the secret on an existing API key.

    Generates a fresh plaintext, replaces ``key_prefix`` and
    ``key_hash`` in place, and returns the new plaintext exactly once.
    Rotation is only permitted on the caller's own active keys;
    revoked keys cannot be rotated (the caller must create a new key
    instead). Emits an ``api_key.rotate`` audit row.

    Args:
        key_id: The id of the key to rotate.
        request: Inbound request, for audit attribution.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        The :class:`ApiKeyRotateOut` payload with the new plaintext.

    Raises:
        HTTPException: 404 when the key is unknown or owned by a
            different user, 409 ``api_key_revoked`` when the key has
            already been revoked.
    """
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.user_id == principal.user.id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "api_key_not_found"},
        )
    if row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "api_key_revoked"},
        )

    new_plaintext, new_prefix, new_hash = generate_plaintext(_PLAINTEXT_ENV)
    row.key_prefix = new_prefix
    row.key_hash = new_hash
    await db.flush()

    await log_audit(
        db,
        action="api_key.rotate",
        user_id=principal.user.id,
        resource_type="api_key",
        resource_id=row.id,
        details={"key_id": row.id, "name": row.name},
        request=request,
    )

    await db.commit()
    await db.refresh(row)

    now = datetime.now(timezone.utc)
    threshold = timedelta(days=settings.api_key_inactivity_threshold_days)
    payload = _build_out_payload(row, now, threshold)
    payload["plaintext"] = new_plaintext
    return ApiKeyRotateOut(**payload)


@router.post(
    "/{key_id}/revoke",
    response_model=ApiKeyOut,
    summary="Revoke an API key",
    description=(
        "Mark the key as permanently inert by stamping ``revoked_at``. "
        "The operation is idempotent: revoking an already-revoked key "
        "returns the row unchanged and emits no duplicate audit row."
    ),
)
async def revoke_api_key(
    key_id: str,
    request: Request,
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyOut:
    """Revoke an API key owned by the caller.

    Sets ``revoked_at`` to the current timestamp; the key is then
    permanently rejected by the auth resolver per Req 2.5. The
    operation is idempotent: a second revoke on an already-revoked
    key returns the row unchanged and does not emit a duplicate
    audit row.

    Args:
        key_id: The id of the key to revoke.
        request: Inbound request, for audit attribution.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        The :class:`ApiKeyOut` payload reflecting the revoked state.

    Raises:
        HTTPException: 404 when the key is unknown or owned by a
            different user.
    """
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.user_id == principal.user.id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "api_key_not_found"},
        )

    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.flush()

        await log_audit(
            db,
            action="api_key.revoke",
            user_id=principal.user.id,
            resource_type="api_key",
            resource_id=row.id,
            details={"key_id": row.id, "name": row.name},
            request=request,
        )
        await db.commit()
        await db.refresh(row)

    now = datetime.now(timezone.utc)
    threshold = timedelta(days=settings.api_key_inactivity_threshold_days)
    return ApiKeyOut(**_build_out_payload(row, now, threshold))


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hard-delete a previously revoked API key",
    description=(
        "Permanently remove a revoked key once the audit retention "
        "window has elapsed. Blocked attempts return 409 with a "
        "stable ``reason`` of either ``not_revoked`` or "
        "``retention_pending``."
    ),
)
async def hard_delete_api_key(
    key_id: str,
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hard-delete a previously revoked API key.

    Permitted only when the key has been revoked *and* the audit
    retention floor has elapsed since revocation; the gate is a single
    helper :func:`_can_hard_delete` so the policy lives in one place.
    Blocked attempts return 409 with a stable ``reason`` so the client
    can distinguish "revoke first" from "wait longer".

    No audit row is emitted by the hard delete itself; the prior
    ``api_key.revoke`` event already records the credential's
    terminal lifecycle transition, and the row is destroyed by this
    call.

    Args:
        key_id: The id of the key to delete.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        ``None`` — the response carries HTTP 204.

    Raises:
        HTTPException: 404 when the key is unknown or owned by a
            different user, 409 ``delete_blocked`` with a ``reason``
            of either ``not_revoked`` or ``retention_pending`` when
            the gate denies the request.
    """
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.user_id == principal.user.id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "api_key_not_found"},
        )

    allowed, reason = _can_hard_delete(row, datetime.now(timezone.utc))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "delete_blocked", "reason": reason},
        )

    await db.delete(row)
    await db.commit()
    return None

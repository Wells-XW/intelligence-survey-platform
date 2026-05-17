"""Platform-administrator endpoints for cross-tenant inventory and audit review.

These endpoints implement Component 11 of the design and satisfy
Requirements 9.1, 9.2, 9.3, and 9.4. They expose a small set of
read-mostly inventory routes plus an admin-side force-revoke for API
keys, intended to support compliance review without ad-hoc database
queries.

Authorization model
-------------------

Every route depends on :func:`app.core.deps.get_principal` and is
gated on a single scope label via :func:`app.core.deps.require_scope`:

* ``GET /api-keys`` — ``admin:read``
* ``POST /api-keys/{key_id}/revoke`` — ``admin:write``
* ``GET /webhooks`` — ``admin:read``
* ``GET /exports`` — ``admin:read``
* ``GET /audit-logs`` — ``audit:read``

JWT-authenticated principals always pass scope checks (their RBAC role
is what gates them); API-key-authenticated principals must hold the
specific scope on their stored ``scopes`` list. In addition, every
route enforces ``User.is_admin`` via :func:`_require_is_admin`. This
defends against the case where a JWT token belongs to a non-admin
user: ``require_scope`` waves JWT principals through unconditionally,
so an explicit ``is_admin`` gate is needed to keep the administrative
surface restricted to the platform's admin operators.

Distinct admin-revoke verb
--------------------------

The admin force-revoke path emits ``api_key.admin_revoke`` rather than
the owner-side ``api_key.revoke``. The two verbs share resource type
and id but record different actor identities in ``user_id`` and in
``details``: the audit row's ``user_id`` is the administrator's id, the
``details`` map carries both ``owner_user_id`` and ``admin_user_id``
explicitly. Distinguishing the verbs at the audit layer lets reviewers
separate self-revoke from compliance-driven revoke per Req 9.4.

Trailing 30-day metric provenance
---------------------------------

* The API-key inventory carries ``request_count_30d`` summed at query
  time from the Redis day-window counters that the rate-limit
  middleware writes (key shape
  ``ratelimit:{key_prefix}:d:{epoch_day_start}``). Each counter has a
  TTL slightly larger than 24 hours, so a key that has been quiet
  long enough for every counter in the trailing 30-day window to age
  out yields ``None`` rather than ``0``: the difference matters for
  compliance review because ``0`` claims "we observed no activity"
  whereas ``None`` claims "we have no usable telemetry left". Redis
  outages are absorbed the same way — the field is reported as
  ``None`` rather than failing the request.
* The webhook inventory carries ``failure_count_30d`` derived from a
  ``GROUP BY subscription_id`` count over ``webhook_deliveries``
  filtered to ``status='failed_permanent'`` and ``created_at`` within
  the trailing 30 days. This is always a non-negative integer; a
  subscription with no permanent failures in the window appears as
  ``0``.

Owner-scope vs admin-scope listings
-----------------------------------

The owner-facing list endpoints in ``api_keys.py`` and ``webhooks.py``
restrict to the caller's own rows; these admin endpoints return rows
across all tenants. The route layer never inspects survey RBAC for
the admin reads — the ``admin:read`` scope plus ``is_admin`` flag is
the authorization boundary, consistent with design §Component 11.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.audit import log_audit
from ...core.deps import Principal, require_scope
from ...database import get_db
from ...models.api_key import ApiKey
from ...models.export_job import ExportJob
from ...models.webhook_delivery import WebhookDelivery
from ...models.webhook_subscription import WebhookSubscription
from ...schemas.admin import (
    AdminApiKeyOut,
    AdminAuditLogOut,
    AdminExportJobOut,
    AdminWebhookSubscriptionOut,
)
from ...services.audit_query import query_audit_logs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Module constants ──────────────────────────────────────────────────

#: Width of the trailing window used by both ``request_count_30d`` and
#: ``failure_count_30d`` per Requirements 9.1 and 9.2. Held as a
#: module constant so the two metrics use the same window without
#: drifting independently.
_METRIC_WINDOW_DAYS: int = 30

#: Hard upper bound on rows returned by the audit-logs and exports
#: list endpoints. Mirrors the cap used by
#: :mod:`app.services.audit_query` and keeps response sizes bounded
#: for compliance review.
_LIST_MAX_LIMIT: int = 500

#: Default page size for the audit-logs and exports list endpoints.
_LIST_DEFAULT_LIMIT: int = 100


# ── Helpers ───────────────────────────────────────────────────────────


def _require_is_admin(principal: Principal) -> None:
    """Raise 403 when the principal's user is not flagged as platform admin.

    ``require_scope`` lets JWT principals through unconditionally
    because their RBAC role is what gates them at the resource level.
    The administrative surface needs a stricter check: even a
    JWT-authenticated user without ``is_admin`` must be turned away.
    For API-key principals, ``is_admin`` was already enforced at key
    creation time (admin scopes can only be minted on an admin
    user's behalf), but checking it again here is cheap and keeps the
    invariant local to the admin router.

    Args:
        principal: The resolved request principal.

    Raises:
        HTTPException: 403 with machine code ``admin_only`` when the
            principal's ``user.is_admin`` is False.
    """
    if not getattr(principal.user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "admin_only"},
        )


def _build_admin_api_key_payload(
    row: ApiKey,
    request_count_30d: Optional[int],
) -> AdminApiKeyOut:
    """Project an :class:`ApiKey` row into the admin response shape.

    Pulled out of the route body so the same projection is used by
    both the inventory list and the admin-revoke response.

    Args:
        row: The :class:`ApiKey` row.
        request_count_30d: Trailing 30-day request count, or ``None``
            when no day-window counters remain in Redis.

    Returns:
        The :class:`AdminApiKeyOut` payload.
    """
    return AdminApiKeyOut(
        id=row.id,
        owner_user_id=row.user_id,
        name=row.name,
        key_prefix=row.key_prefix,
        scopes=list(row.scopes or []),
        rate_limit_overrides=row.rate_limit_overrides,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
        request_count_30d=request_count_30d,
    )


async def _compute_30d_request_counts(
    key_prefixes: List[str],
) -> Dict[str, Optional[int]]:
    """Sum Redis day-window counters across the last 30 days per key.

    Reads the counters that the rate-limit middleware writes under
    ``ratelimit:{key_prefix}:d:{epoch_day_start}``. The middleware
    sets a TTL slightly larger than 24 hours on each counter, so days
    that have already aged out appear as missing keys. We use
    ``MGET`` to fetch every counter for every prefix in a single
    round trip per prefix.

    Reporting rule:
        When *every* day-window key is missing for a given prefix the
        result is ``None`` (no usable telemetry remains). Otherwise
        we sum the present counters, treating missing days as zero.
        This preserves the distinction between "key is genuinely
        quiet" (some counters present, sum may be 0) and "key has
        already expired in Redis" (no counters present, ``None``).

    Failure handling:
        Any Redis failure is absorbed and yields ``None`` for every
        prefix. Compliance review must not be blocked by an
        infrastructure outage in the rate-limit telemetry path.

    Args:
        key_prefixes: List of API-key prefixes (the 11-character
            prefix the rate limiter uses as its identity).

    Returns:
        Mapping from each prefix to either an integer count or
        ``None`` per the reporting rule above.
    """
    if not key_prefixes:
        return {}

    try:
        import redis.asyncio as aioredis  # local import keeps Redis optional

        client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=1.0,
            socket_connect_timeout=1.0,
        )
    except Exception:  # noqa: BLE001 — Redis must not block the admin path
        logger.warning("Failed to construct Redis client for 30d counts", exc_info=True)
        return {prefix: None for prefix in key_prefixes}

    try:
        now = int(datetime.now(timezone.utc).timestamp())
        day_seconds = 86400
        # Newest day first; one entry per day in the window.
        day_starts = [
            (now // day_seconds) * day_seconds - i * day_seconds
            for i in range(_METRIC_WINDOW_DAYS)
        ]

        counts: Dict[str, Optional[int]] = {}
        for prefix in key_prefixes:
            keys = [f"ratelimit:{prefix}:d:{ds}" for ds in day_starts]
            try:
                values = await client.mget(*keys)
            except Exception:  # noqa: BLE001 — degrade per-prefix
                logger.warning(
                    "Redis MGET failed for key_prefix=%s", prefix, exc_info=True
                )
                counts[prefix] = None
                continue

            if all(v is None for v in values):
                counts[prefix] = None
            else:
                counts[prefix] = sum(int(v) for v in values if v is not None)
        return counts
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001 — close errors are non-fatal
            logger.debug("Redis client close raised", exc_info=True)


async def _compute_30d_failure_counts(
    db: AsyncSession,
    subscription_ids: List[str],
) -> Dict[str, int]:
    """Count permanent webhook failures per subscription over the 30-day window.

    Performs a single ``GROUP BY`` query over ``webhook_deliveries``
    filtered to ``status='failed_permanent'`` and ``created_at >=
    now - 30 days``, restricted to the supplied subscription ids.
    Subscriptions with no failures in the window are absent from the
    return mapping; callers should default missing keys to zero.

    Args:
        db: Active async database session.
        subscription_ids: Subscription ids to compute failure counts
            for. The empty list short-circuits to an empty mapping.

    Returns:
        Mapping from subscription id to its failure count over the
        trailing 30-day window (only subscriptions with at least one
        failure are present).
    """
    if not subscription_ids:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=_METRIC_WINDOW_DAYS)
    stmt = (
        select(WebhookDelivery.subscription_id, func.count())
        .where(
            WebhookDelivery.subscription_id.in_(subscription_ids),
            WebhookDelivery.status == "failed_permanent",
            WebhookDelivery.created_at >= cutoff,
        )
        .group_by(WebhookDelivery.subscription_id)
    )
    result = await db.execute(stmt)
    return {sub_id: int(count) for sub_id, count in result.all()}


# ── Routes ────────────────────────────────────────────────────────────


@router.get(
    "/api-keys",
    response_model=List[AdminApiKeyOut],
    summary="List every non-revoked API key across all tenants",
    description=(
        "Return the cross-tenant inventory of active API keys with "
        "each key's owner identity and a trailing 30-day request "
        "count. Restricted to ``admin:read`` scope plus the platform "
        "``is_admin`` flag."
    ),
)
async def list_all_api_keys(
    principal: Principal = Depends(require_scope("admin:read")),
    db: AsyncSession = Depends(get_db),
) -> List[AdminApiKeyOut]:
    """List every non-revoked API key across all tenants.

    Returns the complete inventory of active API keys with each key's
    ``owner_user_id`` and a trailing 30-day request count derived from
    Redis day-window counters. Per Req 9.1 the response is restricted
    to non-revoked keys; revoked keys are omitted entirely (they are
    visible only via the audit log). When the underlying tables are
    empty the response is an empty list, consistent with the
    "returning an empty list when no non-revoked API_Keys exist"
    clause of Req 9.1.

    Args:
        principal: Caller resolved by :func:`require_scope` for
            ``admin:read``; additionally must carry ``is_admin``.
        db: Async database session.

    Returns:
        Newest-first list of :class:`AdminApiKeyOut` payloads.
    """
    _require_is_admin(principal)

    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
    )
    rows = list(result.scalars().all())

    request_counts = await _compute_30d_request_counts(
        [row.key_prefix for row in rows]
    )

    return [
        _build_admin_api_key_payload(
            row, request_counts.get(row.key_prefix)
        )
        for row in rows
    ]


@router.post(
    "/api-keys/{key_id}/revoke",
    response_model=AdminApiKeyOut,
    summary="Force-revoke an API key on behalf of compliance",
    description=(
        "Set ``revoked_at`` on a key without requiring the owner's "
        "consent. Emits the distinct ``api_key.admin_revoke`` audit "
        "verb so reviewers can separate self-revoke from "
        "compliance-driven revoke. Restricted to ``admin:write`` "
        "scope plus the platform ``is_admin`` flag."
    ),
)
async def admin_revoke_api_key(
    key_id: str,
    request: Request,
    principal: Principal = Depends(require_scope("admin:write")),
    db: AsyncSession = Depends(get_db),
) -> AdminApiKeyOut:
    """Force-revoke an API key on behalf of compliance.

    Mirrors the effects of owner self-revocation in ``api_keys.py``:
    sets ``revoked_at`` on the row and marks the key permanently
    inert. The distinguishing behaviour is the audit verb. Where
    owner self-revoke writes ``api_key.revoke`` with the owner as
    actor, this path writes ``api_key.admin_revoke`` with the
    administrator as actor and embeds both ``owner_user_id`` and
    ``admin_user_id`` in the audit ``details``. Reviewers can
    therefore separate self-revoke from compliance-driven revoke
    without traversing the ``users`` table.

    The operation is idempotent: revoking an already-revoked key
    returns the row unchanged and does not emit a duplicate audit
    row.

    Args:
        key_id: UUID of the key to revoke.
        request: Inbound request, used for audit attribution
            (IP and user-agent).
        principal: Caller resolved by :func:`require_scope` for
            ``admin:write``; additionally must carry ``is_admin``.
        db: Async database session.

    Returns:
        The :class:`AdminApiKeyOut` payload reflecting the revoked
        state. The 30-day request count is reported as ``None`` on
        the revoke response — admins consulting telemetry should use
        the inventory endpoint, which reads counters fresh.

    Raises:
        HTTPException: 404 ``api_key_not_found`` when the key does
            not exist.
    """
    _require_is_admin(principal)

    row = await db.get(ApiKey, key_id)
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
            action="api_key.admin_revoke",
            user_id=principal.user.id,
            resource_type="api_key",
            resource_id=row.id,
            details={
                "key_id": row.id,
                "name": row.name,
                "owner_user_id": row.user_id,
                "admin_user_id": principal.user.id,
            },
            request=request,
        )
        await db.commit()
        await db.refresh(row)

    return _build_admin_api_key_payload(row, request_count_30d=None)


@router.get(
    "/webhooks",
    response_model=List[AdminWebhookSubscriptionOut],
    summary="List every active webhook subscription across all tenants",
    description=(
        "Return the cross-tenant inventory of active webhook "
        "subscriptions with each subscription's owner identity and a "
        "trailing 30-day permanent-failure count. Restricted to "
        "``admin:read`` scope plus the platform ``is_admin`` flag."
    ),
)
async def list_all_webhooks(
    principal: Principal = Depends(require_scope("admin:read")),
    db: AsyncSession = Depends(get_db),
) -> List[AdminWebhookSubscriptionOut]:
    """List every active webhook subscription across all tenants.

    Returns the complete inventory of active subscriptions with each
    subscription's ``owner_user_id`` and a 30-day permanent-failure
    count drawn from ``webhook_deliveries``. Per Req 9.2 the response
    is restricted to ``active=True`` subscriptions; soft-deleted
    subscriptions (``active=False``) are omitted. When no active
    subscriptions exist the response is an empty list, consistent
    with the "returning an empty list when no active subscriptions
    exist" clause of Req 9.2.

    Args:
        principal: Caller resolved by :func:`require_scope` for
            ``admin:read``; additionally must carry ``is_admin``.
        db: Async database session.

    Returns:
        Newest-first list of
        :class:`AdminWebhookSubscriptionOut` payloads.
    """
    _require_is_admin(principal)

    result = await db.execute(
        select(WebhookSubscription)
        .where(WebhookSubscription.active.is_(True))
        .order_by(WebhookSubscription.created_at.desc())
    )
    subs = list(result.scalars().all())

    failure_counts = await _compute_30d_failure_counts(
        db, [s.id for s in subs]
    )

    return [
        AdminWebhookSubscriptionOut(
            id=s.id,
            owner_user_id=s.user_id,
            survey_id=s.survey_id,
            target_url=s.target_url,
            event_types=list(s.event_types or []),
            description=s.description,
            active=s.active,
            last_delivery_at=s.last_delivery_at,
            last_delivery_status=s.last_delivery_status,
            created_at=s.created_at,
            updated_at=s.updated_at,
            failure_count_30d=failure_counts.get(s.id, 0),
        )
        for s in subs
    ]


@router.get(
    "/exports",
    response_model=List[AdminExportJobOut],
    summary="List export jobs across all tenants",
    description=(
        "Return the cross-tenant inventory of export jobs filtered "
        "by an optional time range. Each row carries the owner "
        "identity, the survey, the format, the lifecycle status, and "
        "the materialized byte size when present. Restricted to "
        "``admin:read`` scope plus the platform ``is_admin`` flag."
    ),
)
async def list_all_exports(
    since: Optional[datetime] = Query(
        default=None,
        description=(
            "Optional inclusive lower bound on ExportJob.created_at. "
            "Use to scope the inventory to a specific compliance "
            "review window."
        ),
    ),
    until: Optional[datetime] = Query(
        default=None,
        description=(
            "Optional exclusive upper bound on ExportJob.created_at. "
            "Combined with ``since`` to bracket the review window."
        ),
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
    limit: int = Query(
        default=_LIST_DEFAULT_LIMIT,
        ge=1,
        le=_LIST_MAX_LIMIT,
        description=(
            "Maximum rows to return. Capped at "
            f"{_LIST_MAX_LIMIT} to keep responses bounded for "
            "compliance review."
        ),
    ),
    principal: Principal = Depends(require_scope("admin:read")),
    db: AsyncSession = Depends(get_db),
) -> List[AdminExportJobOut]:
    """List export jobs across all tenants for the requested time range.

    Per Req 9.3 the response carries every job created in the
    requested time range with its ``owner_user_id``, ``survey_id``,
    ``format``, ``status``, and ``byte_size``. The time range is
    optional: omitting both ``since`` and ``until`` returns the full
    ``ExportJob`` table (capped by ``limit``). The endpoint orders
    rows by ``created_at`` descending so the newest activity surfaces
    first.

    Args:
        since: Optional inclusive lower bound on ``created_at``.
        until: Optional exclusive upper bound on ``created_at``.
        offset: Pagination offset.
        limit: Page size, capped at ``_LIST_MAX_LIMIT``.
        principal: Caller resolved by :func:`require_scope` for
            ``admin:read``; additionally must carry ``is_admin``.
        db: Async database session.

    Returns:
        Newest-first list of :class:`AdminExportJobOut` payloads.
    """
    _require_is_admin(principal)

    stmt = select(ExportJob)
    if since is not None:
        stmt = stmt.where(ExportJob.created_at >= since)
    if until is not None:
        stmt = stmt.where(ExportJob.created_at < until)
    stmt = stmt.order_by(ExportJob.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    return [
        AdminExportJobOut(
            id=row.id,
            owner_user_id=row.user_id,
            survey_id=row.survey_id,
            format=row.format,
            status=row.status,
            options=row.options,
            byte_size=row.byte_size,
            error_message=row.error_message,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            expires_at=row.expires_at,
        )
        for row in rows
    ]


@router.get(
    "/audit-logs",
    response_model=List[AdminAuditLogOut],
    summary="Query the audit log with optional filters",
    description=(
        "Return audit rows newest-first, filtered by any combination "
        "of acting user, resource, action verb, and time range. "
        "Restricted to the ``audit:read`` scope plus the platform "
        "``is_admin`` flag — audit review is a stricter privilege "
        "than the general admin inventory reads."
    ),
)
async def list_audit_logs(
    actor_user_id: Optional[str] = Query(
        default=None,
        description="Filter on AuditLog.user_id (the acting user).",
    ),
    resource_type: Optional[str] = Query(
        default=None,
        description=(
            "Filter on AuditLog.resource_type "
            "(e.g. ``api_key``, ``webhook_subscription``)."
        ),
    ),
    resource_id: Optional[str] = Query(
        default=None,
        description="Filter on AuditLog.resource_id.",
    ),
    action: Optional[str] = Query(
        default=None,
        description=(
            "Exact action verb to filter on (e.g. "
            "``api_key.admin_revoke``)."
        ),
    ),
    since: Optional[datetime] = Query(
        default=None,
        description="Inclusive lower bound on AuditLog.created_at.",
    ),
    until: Optional[datetime] = Query(
        default=None,
        description="Exclusive upper bound on AuditLog.created_at.",
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
    limit: int = Query(
        default=_LIST_DEFAULT_LIMIT,
        ge=1,
        le=_LIST_MAX_LIMIT,
        description=(
            "Maximum rows to return. Capped at "
            f"{_LIST_MAX_LIMIT} to keep responses bounded for "
            "compliance review."
        ),
    ),
    principal: Principal = Depends(require_scope("audit:read")),
    db: AsyncSession = Depends(get_db),
) -> List[AdminAuditLogOut]:
    """Query the audit log with optional filters.

    Thin wrapper over
    :func:`app.services.audit_query.query_audit_logs`. Every filter
    parameter is optional and combined with AND semantics; results
    are returned newest-first. The endpoint is gated on the
    ``audit:read`` scope per design §Component 11 because audit
    review is a stricter privilege than the general ``admin:read``
    inventory: an admin operator may legitimately list the inventory
    without being entitled to inspect actor-attributed audit history.

    Args:
        actor_user_id: Optional filter on ``AuditLog.user_id``.
        resource_type: Optional filter on ``AuditLog.resource_type``.
        resource_id: Optional filter on ``AuditLog.resource_id``.
        action: Optional exact action-verb filter.
        since: Optional inclusive lower bound on ``created_at``.
        until: Optional exclusive upper bound on ``created_at``.
        offset: Pagination offset.
        limit: Page size, capped at ``_LIST_MAX_LIMIT``.
        principal: Caller resolved by :func:`require_scope` for
            ``audit:read``; additionally must carry ``is_admin``.
        db: Async database session.

    Returns:
        Newest-first list of :class:`AdminAuditLogOut` payloads.
    """
    _require_is_admin(principal)

    rows = await query_audit_logs(
        db,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        since=since,
        until=until,
        offset=offset,
        limit=limit,
    )

    return [
        AdminAuditLogOut(
            id=row.id,
            user_id=row.user_id,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            details=row.details,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            created_at=row.created_at,
        )
        for row in rows
    ]

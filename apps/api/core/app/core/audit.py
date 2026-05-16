"""Audit logging utility for PIPL compliance (Article 53)."""

from __future__ import annotations

import logging
from typing import Any, FrozenSet

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.audit_log import AuditLog

logger = logging.getLogger(__name__)


API_PLATFORM_VERBS: FrozenSet[str] = frozenset(
    {
        # API key lifecycle (Req 7.1, 9.4) — feature: API Open Platform
        "api_key.create",
        "api_key.rotate",
        "api_key.revoke",
        "api_key.admin_revoke",
        # Webhook subscription configuration (Req 7.2)
        "webhook.subscription.create",
        "webhook.subscription.update",
        "webhook.subscription.rotate_secret",
        "webhook.subscription.delete",
        # Webhook delivery outcomes (Req 7.3)
        "webhook.delivery.succeeded",
        "webhook.delivery.failed",
        # Export job lifecycle (Req 7.4)
        "export.job.created",
        "export.job.succeeded",
        "export.job.failed",
        "export.job.expired",
        # Per-API-key rate limiter outcomes (Req 7.5)
        "rate_limit.rejected",
        "rate_limiter.backend_unavailable",
    }
)
"""Canonical action verbs emitted by the API Open Platform feature (T15).

These hierarchical dotted verbs are written to ``audit_logs.action`` by the
new API key, webhook, export, and rate-limit subsystems. The existing
``audit_logs`` schema is reused unchanged: each verb stores a row whose
``action`` column holds the verb literal, ``resource_type`` / ``resource_id``
identify the affected entity (e.g. ``api_key``, ``webhook_subscription``,
``webhook_delivery``, ``export_job``, or ``system``), and any extras
(``key_name``, ``target_url``, ``event_type``, ``attempt_count``, ``format``,
``byte_size``, ``window_label``, etc.) flow into the ``details`` JSONB
column. Per Req 7.9, fields that do not fit the schema-compatible subset
are dropped silently rather than triggering a migration.

Other modules import this set to validate or enumerate the new verbs::

    from app.core.audit import API_PLATFORM_VERBS

    assert "api_key.create" in API_PLATFORM_VERBS

The set is intentionally a ``frozenset`` so callers cannot mutate the
canonical registry at runtime.
"""


async def log_audit(
    db: AsyncSession,
    *,
    action: str,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Write an immutable audit log entry.

    This is a fire-and-forget operation — it calls ``db.flush()`` but
    does not commit (the caller's transaction handles that).

    Args:
        db: Active database session.
        action: Action category, e.g. ``"auth.login"``, ``"survey.create"``.
        user_id: UUID of the acting user (None for anonymous actions).
        resource_type: Type of resource affected, e.g. ``"survey"``.
        resource_id: UUID of the resource affected.
        details: Arbitrary JSON-serializable context.
        request: Starlette Request for IP / User-Agent extraction.
    """
    ip_address = None
    user_agent = None
    if request is not None:
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    db.add(entry)
    try:
        await db.flush()
    except Exception:
        logger.exception("Failed to write audit log entry (action=%s)", action)

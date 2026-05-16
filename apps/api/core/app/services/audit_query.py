"""Read-only query helpers for the audit log.

Used by the admin audit-logs endpoint (Task 15.1) to satisfy
Requirement 7.7: filtered, paginated read access to ``audit_logs``
ordered by recency. The same helper is the entry point for the T10
PIPL/GDPR compliance export described in design §10 / Req 9.5: the
compliance reviewer (or its caller) supplies only ``since`` / ``until``
and reads every row in that window — there is intentionally no verb
whitelist, so audit verbs introduced by later features (including the
T15 API Open Platform set in :data:`app.core.audit.API_PLATFORM_VERBS`)
appear in the export automatically.

Rights Tier: this module reads from the canonical ``audit_logs`` table
which itself stores PIPL Article 53 audit trail rows. Callers must enforce
``audit:read`` scope before invoking these helpers; this module does not
perform authorization.
"""

from __future__ import annotations

from datetime import datetime
from typing import FrozenSet, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import API_PLATFORM_VERBS
from ..models.audit_log import AuditLog


# T17.1 compliance-export whitelist sentinel.
#
# The T10 PIPL/GDPR compliance export selects rows by time range only and
# does NOT apply a verb whitelist (see module docstring). This module-level
# constant is the explicit anchor of that contract: ``None`` means "no
# whitelist; every verb in the requested time range is exported".
#
# If a future change ever switches this to a non-empty ``frozenset``, the
# smoke check below guarantees the whitelist remains a superset of
# :data:`API_PLATFORM_VERBS`, so the verbs introduced by T15 (API key,
# webhook subscription, webhook delivery, export job, rate-limit) keep
# flowing through the export per Req 9.5.
_COMPLIANCE_EXPORT_VERB_WHITELIST: Optional[FrozenSet[str]] = None

if _COMPLIANCE_EXPORT_VERB_WHITELIST is not None:
    _missing = API_PLATFORM_VERBS - _COMPLIANCE_EXPORT_VERB_WHITELIST
    assert not _missing, (
        "T10 compliance export whitelist is missing T15 API Open Platform "
        f"verbs: {sorted(_missing)} (Req 9.5)."
    )


async def query_audit_logs(
    db: AsyncSession,
    *,
    actor_user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    action: Optional[str] = None,
    actions: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 100,
) -> List[AuditLog]:
    """Query the audit_logs table with optional filters.

    All filter parameters are optional and combined with AND semantics
    (except ``actions`` which is an OR-filter on the ``action`` column).
    Returns rows ordered by ``created_at`` descending.

    Args:
        db: Active async database session.
        actor_user_id: Optional filter on ``AuditLog.user_id`` (the actor
            who performed the action).
        resource_type: Optional filter on ``AuditLog.resource_type``
            (e.g. ``"api_key"``, ``"webhook_subscription"``).
        resource_id: Optional filter on ``AuditLog.resource_id``.
        action: Optional single action verb filter (exact match).
        actions: Optional list of action verbs (OR-match). Cannot be
            combined with ``action``.
        since: Optional inclusive lower bound on ``created_at``.
        until: Optional exclusive upper bound on ``created_at``.
        offset: Pagination offset (default 0).
        limit: Maximum rows to return (default 100). Callers should cap
            this server-side to a sensible maximum.

    Returns:
        List of ``AuditLog`` rows ordered by ``created_at`` descending.

    Raises:
        ValueError: If both ``action`` and ``actions`` are supplied.
    """
    if action is not None and actions is not None:
        raise ValueError("Pass either action or actions, not both")

    stmt = select(AuditLog)
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.user_id == actor_user_id)
    if resource_type is not None:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if actions:
        stmt = stmt.where(AuditLog.action.in_(actions))
    if since is not None:
        stmt = stmt.where(AuditLog.created_at >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.created_at < until)

    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())

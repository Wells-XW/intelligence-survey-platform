"""Audit logging utility for PIPL compliance (Article 53)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.audit_log import AuditLog

logger = logging.getLogger(__name__)


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

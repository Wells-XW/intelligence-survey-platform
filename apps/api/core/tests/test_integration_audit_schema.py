"""Task 18.5 — Audit schema conformance integration test.

Validates that every T15 audit verb persists through the existing
``audit_logs`` schema unchanged, that the JSONB ``details`` column
round-trips arbitrary nested structures losslessly, and that system
events (``user_id IS NULL``) are accepted.

Validates: Requirements 7.8, 7.9
"""

import pytest
from sqlalchemy import select

from app.core.audit import API_PLATFORM_VERBS, log_audit
from app.models.audit_log import AuditLog


@pytest.mark.asyncio
async def test_all_t15_audit_verbs_persist(db_session):
    """Every verb in API_PLATFORM_VERBS round-trips through audit_logs."""
    for verb in sorted(API_PLATFORM_VERBS):
        await log_audit(
            db_session,
            action=verb,
            user_id=None,
            resource_type="test",
            resource_id=None,
            details={"verb": verb},
        )
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog.action).where(AuditLog.resource_type == "test")
    )
    persisted = {row[0] for row in result.all()}
    assert persisted == set(API_PLATFORM_VERBS)


@pytest.mark.asyncio
async def test_audit_details_jsonb_round_trips(db_session):
    """The JSONB ``details`` column preserves arbitrary nested structure."""
    payload = {
        "key_prefix": "sk_live_ab",
        "scopes": ["survey:read", "response:read"],
        "nested": {"a": 1, "b": [True, None, 3.14]},
    }
    await log_audit(
        db_session,
        action="api_key.create",
        user_id=None,
        resource_type="api_key",
        resource_id="example-id",
        details=payload,
    )
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog.details).where(AuditLog.resource_id == "example-id")
    )
    stored = result.scalar_one()
    assert stored == payload


@pytest.mark.asyncio
async def test_audit_log_does_not_require_user_id(db_session):
    """System events (``user_id=None``) persist successfully."""
    await log_audit(
        db_session,
        action="rate_limiter.backend_unavailable",
        user_id=None,
        resource_type="system",
        resource_id=None,
        details={"reason": "redis_unavailable"},
    )
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "rate_limiter.backend_unavailable"
        )
    )
    row = result.scalar_one()
    assert row.user_id is None

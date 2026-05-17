"""Property test P21: Audit row schema conformance.

Per design.md §Property 21 (Requirements 7.8, 7.9), every audit row
the API platform emits — across api-key lifecycle, webhook
configuration, webhook delivery outcomes, export-job lifecycle, and
rate-limit outcomes — must persist through the existing T10
``audit_logs`` schema unchanged. The persisted row must carry the
seven core fields the design names canonical, mapped onto the
existing column names: ``user_id`` (the actor), ``action`` (the
event verb), ``resource_type`` (the target type), ``resource_id``
(the target id), ``details`` (the JSONB extras), plus the
denormalised ``ip_address`` / ``user_agent`` / ``created_at``
columns.

The brief from the task list reframes the seven core fields with
spec-tier nomenclature ``actor / actor_type / event_verb /
target_type / target_id / principal_id / details_json``. The
mapping onto the live schema is:

* ``actor`` → ``audit_logs.user_id`` (UUID of the user that
  initiated the action; ``NULL`` for system events).
* ``actor_type`` → derived from the resolved auth path; not stored
  on the row, but every emitter populates either ``user_id`` (a
  human or service account) or leaves it ``NULL`` (a system
  emission such as the rate-limiter outage path).
* ``event_verb`` → ``audit_logs.action`` (must be a member of
  ``API_PLATFORM_VERBS``).
* ``target_type`` → ``audit_logs.resource_type`` (e.g.
  ``"api_key"``, ``"webhook_subscription"``, ``"export_job"``,
  ``"system"``).
* ``target_id`` → ``audit_logs.resource_id`` (the affected entity
  id; ``NULL`` only on system events whose target is the platform
  itself).
* ``principal_id`` → ``audit_logs.user_id`` again (same column;
  the spec splits actor from principal, but the existing schema
  collapses them into one field — system events legitimately
  carry ``NULL``).
* ``details_json`` → ``audit_logs.details`` (must be JSONB and
  must round-trip the ``details`` payload the emitter handed in).

Strategy
--------

The verb axis is a fixed sixteen-element frozenset; Hypothesis on
that dimension would be wasteful. We parametrize on the verbs
instead and, for each verb, drive the underlying emission by the
shortest path that exercises the production code path:

* HTTP routes for owner-side lifecycle verbs that the API surfaces
  to users (api-key create / rotate / revoke,
  webhook-subscription create / update / rotate-secret / delete,
  export-job created, admin-revoke).
* Direct ``await`` on the worker async bodies for verbs the user
  cannot drive synchronously
  (``app.tasks.webhook_tasks._async_deliver_webhook``,
  ``app.tasks.export_tasks._async_materialize_export``,
  ``app.tasks.export_tasks._async_sweep_expired_exports``). The
  Celery task wrappers wrap these in :func:`asyncio.run`, which
  would deadlock under :mod:`pytest-asyncio`; calling the async
  body directly is the standard pattern in this repo's
  state-machine property tests (see
  :mod:`tests.test_property_webhook_delivery_state_machine`).
* Direct invocation of
  :func:`app.middleware.rate_limit.RateLimitMiddleware._emit_rate_limit_rejected_audit`
  and
  :func:`._emit_backend_unavailable_audit` for the two
  rate-limit verbs. Driving the middleware through HTTP would
  require booting a real Redis fixture for the 429 path and
  faulting it for the 503 path; the audit emitters themselves
  are the contract under Property 21, so calling them directly
  is the right surface.

After each emission the test reads the most recent matching row
back through a fresh session and asserts the seven-core-field
contract. This approach scales linearly with the verb count and
fails one verb at a time, which is exactly the grain Property 21
needs: a missing field on, say, ``export.job.expired`` should not
be hidden by a passing row on ``api_key.create``.

Cross-test isolation
--------------------

Each test function takes a fresh ``test_engine`` (per the conftest
fixture) so accumulation across earlier tests is irrelevant. Within
one parametrized run, every row read is filtered by the per-call
``resource_id`` so prior parametrize cases cannot mask the row
under test.

Validates: Requirements 7.8, 7.9
"""

# Feature: api-platform-export, Property 21: Audit row schema conformance

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator, Optional, Tuple

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit import API_PLATFORM_VERBS
from app.core.security import create_access_token, hash_password
from app.core.webhook_secret_crypto import encrypt_signing_secret
from app.database import get_db
from app.main import app
from app.middleware.rate_limit import RateLimitMiddleware
from app.models.audit_log import AuditLog
from app.models.export_job import ExportJob
from app.models.survey import Survey
from app.models.survey_permission import SurveyPermission
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_subscription import WebhookSubscription
from app.tasks import export_tasks, webhook_tasks


# ── Module constants ─────────────────────────────────────────────────

#: Verbs the rate-limiter middleware emits with ``user_id = NULL``.
#: These are system events whose principal is the platform itself,
#: so the seven-core-field check loosens "principal_id non-null" to
#: an explicit allow-list. Property 21 carries forward this carve-out
#: from the existing T10 schema, where ``user_id`` is nullable.
_SYSTEM_EVENT_VERBS = frozenset(
    {
        "rate_limit.rejected",
        "rate_limiter.backend_unavailable",
    }
)

#: Verbs whose ``resource_id`` is allowed to be ``NULL``. The
#: rate-limit emitters do not target a single ``api_keys`` row by
#: id (the middleware identifies callers by ``key_prefix`` to keep
#: latency bounded; see middleware module docstring) and the
#: backend-unavailable verb's resource is the platform itself.
_NO_RESOURCE_ID_VERBS = frozenset(
    {
        "rate_limit.rejected",
        "rate_limiter.backend_unavailable",
    }
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def p21_session_factory(test_engine) -> async_sessionmaker:
    """Session factory bound to the function-scoped test engine.

    Every call yields a fresh :class:`AsyncSession` without a
    wrapping ``session.begin()`` so the route layer can commit and
    re-read across phases. Mirrors the
    ``no_txn_db_session`` / ``p10_session_factory`` patterns used
    elsewhere in this test suite.
    """
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest_asyncio.fixture
async def p21_client(
    p21_session_factory: async_sessionmaker,
) -> AsyncIterator[AsyncClient]:
    """HTTP client that injects a fresh route session per request.

    The dependency override returns a brand-new session for each
    ``Depends(get_db)`` resolution so the route's ``await
    db.commit()`` is the natural commit-and-close pattern across
    multiple parametrized cases that share the same engine.
    """

    async def _fresh_route_db() -> AsyncIterator[AsyncSession]:
        async with p21_session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _fresh_route_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def p21_users(
    p21_session_factory: async_sessionmaker,
) -> Tuple[User, User]:
    """Provision an owner user and an admin user, both committed.

    The owner drives every owner-scoped HTTP route; the admin drives
    the admin-revoke route. Per-test uuid suffixes on the email keep
    the unique-email constraint from colliding across cases that
    share the engine.
    """
    async with p21_session_factory() as s:
        owner = User(
            email=f"p21-owner-{uuid.uuid4().hex[:12]}@example.com",
            hashed_password=hash_password("Test1234!"),
            display_name="P21 Owner",
            is_admin=False,
        )
        admin = User(
            email=f"p21-admin-{uuid.uuid4().hex[:12]}@example.com",
            hashed_password=hash_password("Test1234!"),
            display_name="P21 Admin",
            is_admin=True,
        )
        s.add_all([owner, admin])
        await s.commit()
        await s.refresh(owner)
        await s.refresh(admin)
        return owner, admin


# ── Helpers ──────────────────────────────────────────────────────────


def _assert_seven_core_fields(
    row: AuditLog,
    *,
    expected_verb: str,
    expected_resource_type: Optional[str] = None,
    expected_resource_id: Optional[str] = None,
) -> None:
    """Assert the seven-core-field contract on one persisted audit row.

    Maps the canonical names from the spec brief onto the existing
    ``audit_logs`` columns and exercises every clause Property 21
    pins down. The verb membership check is performed first so a
    rogue verb falling outside :data:`API_PLATFORM_VERBS` surfaces
    before any other field is examined.

    Args:
        row: The :class:`AuditLog` row to inspect.
        expected_verb: The verb the emitter under test was supposed
            to write. Must equal ``row.action`` and must be a member
            of :data:`API_PLATFORM_VERBS`.
        expected_resource_type: Optional expected ``resource_type``;
            verified when supplied. Routes for owner-scoped verbs
            always populate this column.
        expected_resource_id: Optional expected ``resource_id``;
            verified when supplied. The two rate-limit verbs are
            allowed to leave this column ``NULL``.

    Raises:
        AssertionError: When any clause of the seven-core-field
            contract fails.
    """
    # Clause 1: event_verb must be a member of API_PLATFORM_VERBS.
    assert row.action in API_PLATFORM_VERBS, (
        f"audit row {row.id} carries verb {row.action!r} which is "
        f"not a member of API_PLATFORM_VERBS"
    )
    assert row.action == expected_verb, (
        f"audit row {row.id} carries verb {row.action!r}; expected "
        f"{expected_verb!r}"
    )

    # Clause 2: actor / principal_id (user_id column). Non-null for
    # owner-driven verbs, allowed null for system events.
    if expected_verb in _SYSTEM_EVENT_VERBS:
        # System events: user_id is allowed to be None and that is
        # the entire point of the system-event carve-out. We do not
        # assert non-null here.
        pass
    else:
        assert row.user_id is not None, (
            f"audit row {row.id} (verb={expected_verb!r}) has "
            f"user_id=None; only system events may leave the "
            f"actor / principal_id NULL"
        )

    # Clause 3: target_type (resource_type column). Required by
    # design §Component 10 on every emission.
    assert row.resource_type is not None, (
        f"audit row {row.id} (verb={expected_verb!r}) has "
        f"resource_type=None; every audit emission must populate "
        f"the target_type"
    )
    if expected_resource_type is not None:
        assert row.resource_type == expected_resource_type, (
            f"audit row {row.id} (verb={expected_verb!r}) has "
            f"resource_type={row.resource_type!r}; expected "
            f"{expected_resource_type!r}"
        )

    # Clause 4: target_id (resource_id column). Required for entity-
    # scoped verbs; the two rate-limit verbs are exempt because the
    # middleware identifies callers by key_prefix rather than by row
    # id (see middleware module docstring "Identity choice and
    # trade-off").
    if expected_verb not in _NO_RESOURCE_ID_VERBS:
        assert row.resource_id is not None, (
            f"audit row {row.id} (verb={expected_verb!r}) has "
            f"resource_id=None; only the two rate-limit system "
            f"verbs may leave the target_id NULL"
        )
        if expected_resource_id is not None:
            assert row.resource_id == expected_resource_id, (
                f"audit row {row.id} (verb={expected_verb!r}) has "
                f"resource_id={row.resource_id!r}; expected "
                f"{expected_resource_id!r}"
            )

    # Clause 5: details_json (details column). Must be a dict (not
    # ``None``, not ``str``, not ``list``); the JSONB column stores
    # the entity context every emitter hands in.
    assert row.details is not None, (
        f"audit row {row.id} (verb={expected_verb!r}) has "
        f"details=None; every audit emission must populate the "
        f"details_json payload"
    )
    assert isinstance(row.details, dict), (
        f"audit row {row.id} (verb={expected_verb!r}) has "
        f"details of type {type(row.details).__name__}; expected "
        f"dict (JSONB object)"
    )

    # Clause 6: created_at must be populated by the model default.
    # Cheap to verify and protects against a future refactor that
    # accidentally drops the default.
    assert row.created_at is not None, (
        f"audit row {row.id} (verb={expected_verb!r}) has "
        f"created_at=None; the model default must populate this"
    )


async def _read_latest_audit_row(
    session_factory: async_sessionmaker,
    *,
    verb: str,
    resource_id: Optional[str] = None,
) -> AuditLog:
    """Return the most recent ``audit_logs`` row matching the verb.

    Filters by ``action == verb`` and, when supplied, by
    ``resource_id == resource_id``. Ordered by descending id so the
    newest emission wins; the test always inspects the row that the
    just-completed emission produced.

    Args:
        session_factory: The per-test session factory.
        verb: The audit verb to filter by.
        resource_id: Optional resource id to scope the read to one
            entity. Required for verbs whose resource id is set so
            the test cannot accidentally inspect a stale row from a
            previous parametrize case.

    Returns:
        The single :class:`AuditLog` row matched.

    Raises:
        AssertionError: When zero rows match.
    """
    async with session_factory() as s:
        stmt = select(AuditLog).where(AuditLog.action == verb)
        if resource_id is not None:
            stmt = stmt.where(AuditLog.resource_id == resource_id)
        stmt = stmt.order_by(AuditLog.id.desc()).limit(1)
        result = await s.execute(stmt)
        row = result.scalar_one_or_none()
        assert row is not None, (
            f"no audit row found for verb={verb!r} "
            f"resource_id={resource_id!r}; emitter under test did "
            f"not write a row"
        )
        return row


async def _make_survey(
    session_factory: async_sessionmaker, owner: User
) -> Survey:
    """Insert a fresh survey owned by ``owner`` plus a viewer permission.

    The survey is needed to satisfy the FK on ``export_jobs`` and
    by the webhook fan-out RBAC gate. The viewer permission row
    grants the owner read access on the survey; this is required
    by :func:`app.core.deps.check_survey_permission` which the
    export-create route calls before inserting the export-job row.
    """
    async with session_factory() as s:
        survey = Survey(
            owner_id=owner.id,
            title="P21 Survey",
            json_content={},
        )
        s.add(survey)
        await s.flush()
        permission = SurveyPermission(
            user_id=owner.id, survey_id=survey.id, role="viewer"
        )
        s.add(permission)
        await s.commit()
        await s.refresh(survey)
        return survey


# ── Tests: HTTP-driven owner-scoped verbs ────────────────────────────


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_api_key_create_schema(
    p21_client: AsyncClient,
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
) -> None:
    """``api_key.create`` carries every core field on a real HTTP run."""
    owner, _admin = p21_users
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    resp = await p21_client.post(
        "/api/v1/api-keys/",
        headers=headers,
        json={
            "name": f"p21-create-{uuid.uuid4().hex[:6]}",
            "scopes": ["survey:read"],
        },
    )
    assert resp.status_code == 201, resp.text
    key_id = resp.json()["id"]

    row = await _read_latest_audit_row(
        p21_session_factory, verb="api_key.create", resource_id=key_id
    )
    _assert_seven_core_fields(
        row,
        expected_verb="api_key.create",
        expected_resource_type="api_key",
        expected_resource_id=key_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_api_key_rotate_schema(
    p21_client: AsyncClient,
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
) -> None:
    """``api_key.rotate`` carries every core field on a real HTTP run."""
    owner, _admin = p21_users
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    create = await p21_client.post(
        "/api/v1/api-keys/",
        headers=headers,
        json={
            "name": f"p21-rotate-{uuid.uuid4().hex[:6]}",
            "scopes": ["survey:read"],
        },
    )
    assert create.status_code == 201
    key_id = create.json()["id"]

    rot = await p21_client.post(
        f"/api/v1/api-keys/{key_id}/rotate", headers=headers
    )
    assert rot.status_code == 200, rot.text

    row = await _read_latest_audit_row(
        p21_session_factory, verb="api_key.rotate", resource_id=key_id
    )
    _assert_seven_core_fields(
        row,
        expected_verb="api_key.rotate",
        expected_resource_type="api_key",
        expected_resource_id=key_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_api_key_revoke_schema(
    p21_client: AsyncClient,
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
) -> None:
    """``api_key.revoke`` carries every core field on a real HTTP run."""
    owner, _admin = p21_users
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    create = await p21_client.post(
        "/api/v1/api-keys/",
        headers=headers,
        json={
            "name": f"p21-revoke-{uuid.uuid4().hex[:6]}",
            "scopes": ["survey:read"],
        },
    )
    assert create.status_code == 201
    key_id = create.json()["id"]

    rev = await p21_client.post(
        f"/api/v1/api-keys/{key_id}/revoke", headers=headers
    )
    assert rev.status_code == 200, rev.text

    row = await _read_latest_audit_row(
        p21_session_factory, verb="api_key.revoke", resource_id=key_id
    )
    _assert_seven_core_fields(
        row,
        expected_verb="api_key.revoke",
        expected_resource_type="api_key",
        expected_resource_id=key_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_api_key_admin_revoke_schema(
    p21_client: AsyncClient,
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
) -> None:
    """``api_key.admin_revoke`` carries every core field via the admin route."""
    owner, admin = p21_users
    owner_headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
    admin_headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}

    create = await p21_client.post(
        "/api/v1/api-keys/",
        headers=owner_headers,
        json={
            "name": f"p21-admin-revoke-{uuid.uuid4().hex[:6]}",
            "scopes": ["survey:read"],
        },
    )
    assert create.status_code == 201
    key_id = create.json()["id"]

    arv = await p21_client.post(
        f"/api/v1/admin/api-keys/{key_id}/revoke", headers=admin_headers
    )
    assert arv.status_code == 200, arv.text

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="api_key.admin_revoke",
        resource_id=key_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="api_key.admin_revoke",
        expected_resource_type="api_key",
        expected_resource_id=key_id,
    )
    assert row.user_id == admin.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_webhook_subscription_create_schema(
    p21_client: AsyncClient,
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
) -> None:
    """``webhook.subscription.create`` carries every core field."""
    owner, _admin = p21_users
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    resp = await p21_client.post(
        "/api/v1/webhooks/",
        headers=headers,
        json={
            "target_url": "https://hooks.example.com/p21",
            "event_types": ["response.created"],
            "description": "P21 schema conformance test",
        },
    )
    assert resp.status_code == 201, resp.text
    sub_id = resp.json()["id"]

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="webhook.subscription.create",
        resource_id=sub_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="webhook.subscription.create",
        expected_resource_type="webhook_subscription",
        expected_resource_id=sub_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_webhook_subscription_update_schema(
    p21_client: AsyncClient,
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
) -> None:
    """``webhook.subscription.update`` carries every core field."""
    owner, _admin = p21_users
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    create = await p21_client.post(
        "/api/v1/webhooks/",
        headers=headers,
        json={
            "target_url": "https://hooks.example.com/p21u",
            "event_types": ["response.created"],
        },
    )
    assert create.status_code == 201
    sub_id = create.json()["id"]

    upd = await p21_client.patch(
        f"/api/v1/webhooks/{sub_id}",
        headers=headers,
        json={"description": "P21 patched"},
    )
    assert upd.status_code == 200, upd.text

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="webhook.subscription.update",
        resource_id=sub_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="webhook.subscription.update",
        expected_resource_type="webhook_subscription",
        expected_resource_id=sub_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_webhook_subscription_rotate_secret_schema(
    p21_client: AsyncClient,
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
) -> None:
    """``webhook.subscription.rotate_secret`` carries every core field."""
    owner, _admin = p21_users
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    create = await p21_client.post(
        "/api/v1/webhooks/",
        headers=headers,
        json={
            "target_url": "https://hooks.example.com/p21r",
            "event_types": ["response.created"],
        },
    )
    assert create.status_code == 201
    sub_id = create.json()["id"]

    rot = await p21_client.post(
        f"/api/v1/webhooks/{sub_id}/rotate-secret", headers=headers
    )
    assert rot.status_code == 200, rot.text

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="webhook.subscription.rotate_secret",
        resource_id=sub_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="webhook.subscription.rotate_secret",
        expected_resource_type="webhook_subscription",
        expected_resource_id=sub_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_webhook_subscription_delete_schema(
    p21_client: AsyncClient,
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
) -> None:
    """``webhook.subscription.delete`` carries every core field."""
    owner, _admin = p21_users
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    create = await p21_client.post(
        "/api/v1/webhooks/",
        headers=headers,
        json={
            "target_url": "https://hooks.example.com/p21d",
            "event_types": ["response.created"],
        },
    )
    assert create.status_code == 201
    sub_id = create.json()["id"]

    delete = await p21_client.delete(
        f"/api/v1/webhooks/{sub_id}", headers=headers
    )
    assert delete.status_code == 204, delete.text

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="webhook.subscription.delete",
        resource_id=sub_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="webhook.subscription.delete",
        expected_resource_type="webhook_subscription",
        expected_resource_id=sub_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_export_job_created_schema(
    p21_client: AsyncClient,
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
) -> None:
    """``export.job.created`` carries every core field on a real HTTP run."""
    owner, _admin = p21_users
    survey = await _make_survey(p21_session_factory, owner)
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    resp = await p21_client.post(
        "/api/v1/exports/",
        headers=headers,
        json={"survey_id": survey.id, "format": "json"},
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    row = await _read_latest_audit_row(
        p21_session_factory, verb="export.job.created", resource_id=job_id
    )
    _assert_seven_core_fields(
        row,
        expected_verb="export.job.created",
        expected_resource_type="export_job",
        expected_resource_id=job_id,
    )
    assert row.user_id == owner.id


# ── Tests: Worker-driven verbs ───────────────────────────────────────


async def _seed_pending_delivery(
    session_factory: async_sessionmaker, owner: User
) -> Tuple[str, str]:
    """Insert a subscription and a pending delivery row.

    Returns ``(subscription_id, delivery_id)``. The delivery is in
    status ``pending`` so the worker async body will treat it as a
    fresh attempt; the test caller then patches the HTTP layer to
    drive the worker to either ``succeeded`` or ``failed_permanent``
    in one call.
    """
    delivery_id = str(uuid.uuid4())
    async with session_factory() as s:
        sub = WebhookSubscription(
            user_id=owner.id,
            survey_id=None,
            target_url="https://hooks.example.com/p21worker",
            event_types=["response.created"],
            signing_secret_ciphertext=encrypt_signing_secret(
                f"whsec_{uuid.uuid4().hex[:24]}"
            ),
            active=True,
        )
        s.add(sub)
        await s.flush()
        sub_id = sub.id

        delivery = WebhookDelivery(
            id=delivery_id,
            subscription_id=sub_id,
            event_type="response.created",
            payload={"event": "p21", "marker": uuid.uuid4().hex},
            status="pending",
            attempt_count=0,
        )
        s.add(delivery)
        await s.commit()
    return sub_id, delivery_id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_webhook_delivery_succeeded_schema(
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``webhook.delivery.succeeded`` carries every core field.

    Drives the worker async body directly with a stubbed
    :meth:`httpx.AsyncClient.post` returning HTTP 200; the worker
    transitions the delivery to ``succeeded`` and emits one audit
    row.
    """
    owner, _admin = p21_users
    _sub_id, delivery_id = await _seed_pending_delivery(
        p21_session_factory, owner
    )

    async def _fake_post(self, url, *, content=None, headers=None):
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    await webhook_tasks._async_deliver_webhook(delivery_id)

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="webhook.delivery.succeeded",
        resource_id=delivery_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="webhook.delivery.succeeded",
        expected_resource_type="webhook_delivery",
        expected_resource_id=delivery_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_webhook_delivery_failed_schema(
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``webhook.delivery.failed`` carries every core field.

    Drives the worker async body with a stubbed POST returning HTTP
    503 and a stubbed ``send_task`` that raises so the retry-enqueue
    path takes the row directly to ``failed_permanent`` in one call
    (Req 4.7), emitting the failure audit row.
    """
    owner, _admin = p21_users
    _sub_id, delivery_id = await _seed_pending_delivery(
        p21_session_factory, owner
    )

    async def _fake_post(self, url, *, content=None, headers=None):
        return SimpleNamespace(status_code=503)

    def _fake_send_task(*args, **kwargs):
        raise RuntimeError("simulated broker outage")

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    monkeypatch.setattr(
        webhook_tasks.celery_app, "send_task", _fake_send_task
    )

    await webhook_tasks._async_deliver_webhook(delivery_id)

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="webhook.delivery.failed",
        resource_id=delivery_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="webhook.delivery.failed",
        expected_resource_type="webhook_delivery",
        expected_resource_id=delivery_id,
    )
    assert row.user_id == owner.id


async def _seed_queued_export_job(
    session_factory: async_sessionmaker,
    owner: User,
    survey: Survey,
    *,
    fmt: str = "json",
) -> str:
    """Insert a fresh queued export job and return its id.

    The worker async body picks the row up, transitions it to
    ``running``, materializes the artifact, and writes the terminal
    audit row when it commits.
    """
    job_id = str(uuid.uuid4())
    async with session_factory() as s:
        job = ExportJob(
            id=job_id,
            user_id=owner.id,
            survey_id=survey.id,
            format=fmt,
            status="queued",
        )
        s.add(job)
        await s.commit()
    return job_id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_export_job_succeeded_schema(
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``export.job.succeeded`` carries every core field.

    Drives the export worker async body directly. The producer
    writes a real JSON file under ``tmp_path`` so the worker's
    atomic ``os.replace`` succeeds and the success audit row fires.
    Storage root is monkeypatched to ``tmp_path`` so test artifacts
    are scoped to the pytest temporary directory and cleaned up
    automatically.
    """
    owner, _admin = p21_users
    survey = await _make_survey(p21_session_factory, owner)

    monkeypatch.setattr(
        export_tasks.settings, "export_storage_root", str(tmp_path)
    )

    job_id = await _seed_queued_export_job(
        p21_session_factory, owner, survey, fmt="json"
    )

    await export_tasks._async_materialize_export(job_id)

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="export.job.succeeded",
        resource_id=job_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="export.job.succeeded",
        expected_resource_type="export_job",
        expected_resource_id=job_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_export_job_failed_schema(
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``export.job.failed`` carries every core field.

    Seeds a queued job with an unsupported ``format`` string and
    drives the materialization worker. The worker's
    :func:`_prepare_running` rejects unsupported formats up front
    with ``error_text="format_unsupported: {fmt}"`` and emits the
    failure audit row before any survey lookup runs, so this path
    does not need FK manipulation. Inserting a row with an
    out-of-band format value is permitted because the
    :class:`ExportJob` ``format`` column is plain ``VARCHAR(20)``;
    the route layer (:func:`app.api.v1.exports.create_export_job`)
    blocks unsupported values at create time, and the worker
    double-checks at materialization time as a defensive guard
    against worker hosts whose ``pyreadstat`` availability differs
    from the API's. This test exercises the worker's defensive
    check directly.
    """
    owner, _admin = p21_users
    survey = await _make_survey(p21_session_factory, owner)

    monkeypatch.setattr(
        export_tasks.settings, "export_storage_root", str(tmp_path)
    )

    # Seed with an unsupported format so the worker's
    # ``_prepare_running`` short-circuits to the failure path.
    job_id = await _seed_queued_export_job(
        p21_session_factory, owner, survey, fmt="not-a-real-format"
    )

    await export_tasks._async_materialize_export(job_id)

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="export.job.failed",
        resource_id=job_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="export.job.failed",
        expected_resource_type="export_job",
        expected_resource_id=job_id,
    )
    assert row.user_id == owner.id


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_export_job_expired_schema(
    p21_session_factory: async_sessionmaker,
    p21_users: Tuple[User, User],
    tmp_path: Path,
) -> None:
    """``export.job.expired`` carries every core field.

    Inserts a succeeded job with a real on-disk artifact whose
    ``expires_at`` is already in the past, then runs the retention
    sweeper async body. The sweeper unlinks the artifact, transitions
    the row to ``expired``, and emits the audit row.
    """
    owner, _admin = p21_users
    survey = await _make_survey(p21_session_factory, owner)

    # Build a real artifact on disk so the sweeper's unlink succeeds
    # and the row state advances. The sweeper is conservative — if
    # the unlink fails it leaves the row in ``succeeded`` and skips
    # the audit emission, so a real file is necessary.
    artifact_dir = tmp_path / owner.id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "export.json"
    artifact_path.write_text("[]", encoding="utf-8")

    job_id = str(uuid.uuid4())
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    async with p21_session_factory() as s:
        job = ExportJob(
            id=job_id,
            user_id=owner.id,
            survey_id=survey.id,
            format="json",
            status="succeeded",
            storage_path=str(artifact_path),
            byte_size=2,
            completed_at=past,
            expires_at=past,
        )
        s.add(job)
        await s.commit()

    await export_tasks._async_sweep_expired_exports()

    row = await _read_latest_audit_row(
        p21_session_factory,
        verb="export.job.expired",
        resource_id=job_id,
    )
    _assert_seven_core_fields(
        row,
        expected_verb="export.job.expired",
        expected_resource_type="export_job",
        expected_resource_id=job_id,
    )
    assert row.user_id == owner.id


# ── Tests: Rate-limiter system verbs ─────────────────────────────────


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_rate_limit_rejected_schema(
    p21_session_factory: async_sessionmaker,
) -> None:
    """``rate_limit.rejected`` carries every core field.

    Calls the middleware's audit-emission helper directly with a
    minimal :class:`Request` shim. The emitter writes one row with
    ``user_id=None`` (the limiter sees a key prefix, not a user id),
    ``resource_type="api_key"``, and ``resource_id=None`` per the
    middleware's "Identity choice and trade-off" docstring.
    """
    middleware = RateLimitMiddleware(app=lambda *args, **kwargs: None)

    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/v1/p21"),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "p21-test"},
    )

    await middleware._emit_rate_limit_rejected_audit(
        api_key_id="sk_live_p21",
        request=request,  # type: ignore[arg-type]
        window="minute",
    )

    row = await _read_latest_audit_row(
        p21_session_factory, verb="rate_limit.rejected"
    )
    _assert_seven_core_fields(
        row,
        expected_verb="rate_limit.rejected",
        expected_resource_type="api_key",
    )
    assert row.user_id is None
    assert row.resource_id is None
    assert row.details.get("key_prefix") == "sk_live_p21"


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8, 7.9
@pytest.mark.asyncio
async def test_p21_rate_limiter_backend_unavailable_schema(
    p21_session_factory: async_sessionmaker,
) -> None:
    """``rate_limiter.backend_unavailable`` carries every core field."""
    middleware = RateLimitMiddleware(app=lambda *args, **kwargs: None)

    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/v1/p21"),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "p21-test"},
    )

    await middleware._emit_backend_unavailable_audit(
        api_key_id="sk_live_p21",
        request=request,  # type: ignore[arg-type]
    )

    row = await _read_latest_audit_row(
        p21_session_factory, verb="rate_limiter.backend_unavailable"
    )
    _assert_seven_core_fields(
        row,
        expected_verb="rate_limiter.backend_unavailable",
        expected_resource_type="system",
    )
    assert row.user_id is None
    assert row.resource_id is None
    assert row.details.get("key_prefix") == "sk_live_p21"


# ── Pre-flight invariants ────────────────────────────────────────────


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8
def test_p21_api_platform_verbs_is_frozenset() -> None:
    """The verb registry is a :class:`frozenset` so callers cannot mutate it.

    A test that mutated the canonical registry mid-run would
    silently corrupt every other property test that consults it.
    Pinning the type here keeps the registry an immutable surface.
    """
    assert isinstance(API_PLATFORM_VERBS, frozenset), (
        f"API_PLATFORM_VERBS must be a frozenset; got "
        f"{type(API_PLATFORM_VERBS).__name__}"
    )


# Feature: api-platform-export, Property 21: Audit row schema conformance
# Validates: Requirements 7.8
def test_p21_every_verb_under_test_is_registered() -> None:
    """Every verb the parametrized cases assert on belongs to the registry.

    A regression that drops a verb from :data:`API_PLATFORM_VERBS`
    would silently skip the seven-core-field check for the
    matching transition. Listing the verbs here surfaces drift
    before the property tests fire.
    """
    expected_verbs = {
        "api_key.create",
        "api_key.rotate",
        "api_key.revoke",
        "api_key.admin_revoke",
        "webhook.subscription.create",
        "webhook.subscription.update",
        "webhook.subscription.rotate_secret",
        "webhook.subscription.delete",
        "webhook.delivery.succeeded",
        "webhook.delivery.failed",
        "export.job.created",
        "export.job.succeeded",
        "export.job.failed",
        "export.job.expired",
        "rate_limit.rejected",
        "rate_limiter.backend_unavailable",
    }
    missing = expected_verbs - API_PLATFORM_VERBS
    assert not missing, (
        f"verbs under test missing from API_PLATFORM_VERBS: "
        f"{sorted(missing)}"
    )
    extra = API_PLATFORM_VERBS - expected_verbs
    assert not extra, (
        f"API_PLATFORM_VERBS carries verbs not covered by P21: "
        f"{sorted(extra)} — extend the test or remove the verb"
    )

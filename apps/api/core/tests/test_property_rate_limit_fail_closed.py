"""Property test P18: Rate-limit fail-closed on Redis outage.

Per design.md §Property 18, when the Redis client raises ``ConnectionError``
or times out during the rate limiter's counter operation for an
API-key-authenticated request, the response MUST be HTTP 503 with body
``{"error": "rate_limiter.backend_unavailable"}``, the route handler MUST NOT
be invoked, and exactly one audit row with action
``rate_limiter.backend_unavailable`` MUST be appended to ``audit_logs``.

This is the security-critical fail-closed behaviour: if the limiter cannot
verify quota, the safe response is to deny rather than allow-by-default.

Strategy
--------

Hypothesis enumerates the variability that matters for this property:

* The Redis exception class raised on the Lua eval call —
  ``redis.exceptions.ConnectionError`` (network unreachable) vs
  ``redis.exceptions.TimeoutError`` (socket timeout). Both must trigger
  the same fail-closed branch.
* The HTTP route used for the test request. The middleware records the
  ``method`` and ``path`` in the audit ``details`` payload, so the
  property must hold across distinct routes; sampling several pins
  any path-specific branch in the audit emitter.

For each generated example we:

1. Patch ``redis.asyncio.client.Redis.eval`` (the Lua call site in the
   middleware) to raise the chosen exception class. Patching at the
   class level forces every API-key request — first or cached client —
   through the fail-closed branch.
2. Wipe ``audit_logs`` so the per-example "exactly one row" assertion
   is scoped to this example.
3. Issue an HTTP request through ``async_client`` carrying an
   ``X-API-Key`` header whose value starts with ``sk_``. The middleware
   only inspects the header to decide whether the request is on the
   API-key path; it does not query the database for the key, so we
   need not provision an ``ApiKey`` row in the test database.
4. Assert the response is HTTP 503 with the documented body, that
   exactly one audit row was appended, and that the route handler did
   not run (the response body has no handler-shaped fields).

Validates: Requirements 6.7
"""

# Feature: api-platform-export, Property 18: Rate-limit fail-closed on Redis outage

from __future__ import annotations

import uuid
from typing import List, Tuple

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings as app_settings
from app.models.audit_log import AuditLog


# Both exception classes must trigger the same fail-closed branch in the
# middleware. ``ConnectionError`` covers the network-unreachable case and
# ``TimeoutError`` covers the socket-timeout case configured by the
# limiter's ``socket_timeout=1.0`` on its lazily-built async client.
_REDIS_EXCEPTIONS = (RedisConnectionError, RedisTimeoutError)


# A fake plaintext that satisfies the middleware's two requirements:
# (1) starts with ``sk_`` so the API-key resolver picks it up, and
# (2) is long enough that ``token[:11]`` returns the documented 11-char
# prefix. The middleware does not look this value up in the database,
# so no ApiKey row is needed.
_FAKE_API_KEY = "sk_live_p18fakekeyplaintext"
assert _FAKE_API_KEY.startswith("sk_")
assert len(_FAKE_API_KEY) >= 11


# A small set of read-only public routes. The middleware short-circuits
# with 503 before the router is reached, so the route does not need to
# exist for the property to hold — but using real routes makes the
# test resemble a production request, and exercises the audit row's
# ``method`` and ``path`` payload across multiple values.
_ROUTES: List[Tuple[str, str]] = [
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/api-keys/"),
    ("GET", "/api/v1/exports/"),
]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest_asyncio.fixture
async def audit_engine():
    """Provide a dedicated engine for reading and truncating audit_logs.

    The middleware emits its audit row through a fresh
    ``app.database.async_session()`` and commits independently of the
    conftest's per-test ``db_session`` (which wraps the test in a
    rollback-at-teardown transaction). Reading through the per-test
    session would therefore miss the committed row, and writing to it
    would close the wrapping transaction. A dedicated engine sidesteps
    both problems and avoids any coupling to ``app.database.engine``,
    which the conftest disposes between tests.

    The engine is function-scoped because asyncpg connections are bound
    to the event loop on which they were created, and pytest-asyncio
    creates one loop per test by default.
    """
    test_db_url = app_settings.database_url.replace(
        "survey_db", "survey_test_db"
    )
    engine = create_async_engine(test_db_url, echo=False)
    yield engine
    await engine.dispose()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def _truncate_audit_logs(engine) -> None:
    """Delete every row from ``audit_logs`` using the audit engine.

    Hypothesis runs many examples per test function, and the middleware
    audit row commits independently of the per-test session, so without
    explicit truncation the row count grows monotonically across
    examples. Wiping at the start of every example keeps the
    "exactly one row appended" assertion scoped to a single request.
    """
    async with engine.begin() as conn:
        await conn.execute(delete(AuditLog))


async def _read_audit_rows_by_action(
    engine, action: str
) -> List[AuditLog]:
    """Return every ``audit_logs`` row whose ``action`` matches.

    Args:
        engine: The dedicated audit engine fixture.
        action: The audit verb to filter on.

    Returns:
        Matching rows ordered by id ascending.
    """
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.action == action)
            .order_by(AuditLog.id.asc())
        )
        return list(result.scalars().all())


def _patch_redis_eval(monkeypatch, exc_cls: type) -> None:
    """Monkeypatch ``redis.asyncio.client.Redis.eval`` to raise ``exc_cls``.

    The middleware's hot path is::

        redis_client = await self._get_redis()
        counts = await redis_client.eval(_LUA_INCR_THREE, 3, *keys, *ttls)

    Patching ``eval`` on the class object makes every call — first or
    cached — raise the desired exception, regardless of whether the
    middleware has built its lazy client yet. Pytest's ``monkeypatch``
    fixture undoes the patch at teardown even if the test raises.
    """

    async def _raise(self, *args, **kwargs):
        raise exc_cls("simulated Redis outage")

    monkeypatch.setattr(aioredis.Redis, "eval", _raise, raising=True)


# --------------------------------------------------------------------------
# Hypothesis strategies
# --------------------------------------------------------------------------


_REDIS_EXCEPTION_STRATEGY = st.sampled_from(_REDIS_EXCEPTIONS)
_ROUTE_STRATEGY = st.sampled_from(_ROUTES)


# --------------------------------------------------------------------------
# Property
# --------------------------------------------------------------------------


# Feature: api-platform-export, Property 18: Rate-limit fail-closed on Redis outage
# Validates: Requirements 6.7
@pytest.mark.asyncio
@given(
    exc_cls=_REDIS_EXCEPTION_STRATEGY,
    route=_ROUTE_STRATEGY,
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p18_rate_limit_fails_closed_on_redis_outage(
    exc_cls: type,
    route: Tuple[str, str],
    async_client,
    audit_engine,
    monkeypatch,
) -> None:
    """An API-key request fails closed (503 + audit) on Redis outage.

    For every combination of Redis exception class and route under test,
    the middleware must:

    1. Reject the request with HTTP 503.
    2. Return body ``{"error": "rate_limiter.backend_unavailable"}``.
    3. Append exactly one ``rate_limiter.backend_unavailable`` audit row
       carrying the request method and path in ``details``.
    4. Not invoke the route handler (verified indirectly: the response
       body is the fail-closed payload, not any handler-rendered shape).
    """
    # Wipe rows from prior Hypothesis examples so the per-example
    # uniqueness assertion below is scoped to this request.
    await _truncate_audit_logs(audit_engine)

    method, path = route

    # Force every Redis Lua eval to raise the chosen exception class.
    _patch_redis_eval(monkeypatch, exc_cls)

    headers = {"X-API-Key": _FAKE_API_KEY}
    if method == "GET":
        response = await async_client.get(path, headers=headers)
    else:  # pragma: no cover — strategy is closed under {"GET"}
        raise AssertionError(f"unexpected method: {method!r}")

    # 1. Fail-closed status code.
    assert response.status_code == 503, (
        f"expected 503 fail-closed, got {response.status_code}: "
        f"{response.text!r} (exc={exc_cls.__name__}, route={route!r})"
    )

    # 2. Documented machine-readable body.
    body = response.json()
    assert body == {"error": "rate_limiter.backend_unavailable"}, (
        f"unexpected body: {body!r}"
    )

    # 3. Exactly one matching audit row was appended.
    audit_rows = await _read_audit_rows_by_action(
        audit_engine, "rate_limiter.backend_unavailable"
    )
    assert len(audit_rows) == 1, (
        f"expected exactly one audit row, got {len(audit_rows)}: "
        f"{[(r.action, r.details) for r in audit_rows]!r}"
    )
    audit_row = audit_rows[0]
    assert audit_row.details is not None
    assert audit_row.details.get("method") == method
    assert audit_row.details.get("path") == path
    # Resource type is "system" since the outage is platform-wide,
    # not scoped to a particular api_key resource.
    assert audit_row.resource_type == "system"

    # 4. Route handler was not invoked. The fail-closed body has only
    # the ``error`` key; any handler-rendered payload would carry
    # additional fields (a user profile, a list of jobs, etc.). This
    # is a structural check rather than a stub-side spy because the
    # middleware short-circuits before the handler is reached.
    assert "id" not in body, (
        f"route handler appears to have run: response carries 'id': {body!r}"
    )
    assert "items" not in body, (
        f"route handler appears to have run: response carries 'items': {body!r}"
    )


# --------------------------------------------------------------------------
# Anchor example tests
# --------------------------------------------------------------------------
#
# These pin two specific failure modes Hypothesis would otherwise have
# to rediscover on every run. They also document the contract in plain
# pytest-friendly form.


@pytest.mark.asyncio
async def test_p18_example_connection_error_returns_503(
    async_client, audit_engine, monkeypatch
) -> None:
    """A ``ConnectionError`` on Lua eval yields 503 + a single audit row."""
    await _truncate_audit_logs(audit_engine)
    _patch_redis_eval(monkeypatch, RedisConnectionError)

    response = await async_client.get(
        "/api/v1/auth/me", headers={"X-API-Key": _FAKE_API_KEY}
    )
    assert response.status_code == 503
    assert response.json() == {"error": "rate_limiter.backend_unavailable"}

    rows = await _read_audit_rows_by_action(
        audit_engine, "rate_limiter.backend_unavailable"
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_p18_example_timeout_error_returns_503(
    async_client, audit_engine, monkeypatch
) -> None:
    """A ``TimeoutError`` on Lua eval yields 503 + a single audit row."""
    await _truncate_audit_logs(audit_engine)
    _patch_redis_eval(monkeypatch, RedisTimeoutError)

    response = await async_client.get(
        "/api/v1/auth/me", headers={"X-API-Key": _FAKE_API_KEY}
    )
    assert response.status_code == 503
    assert response.json() == {"error": "rate_limiter.backend_unavailable"}

    rows = await _read_audit_rows_by_action(
        audit_engine, "rate_limiter.backend_unavailable"
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_p18_jwt_only_request_bypasses_limiter_unaffected(
    async_client, monkeypatch
) -> None:
    """JWT-authenticated requests bypass the limiter and survive a Redis outage.

    The middleware contract says JWT-authenticated callers skip the
    counter path entirely — their RBAC role is what governs them — so
    a Redis outage must not turn a JWT request into a 503. This guards
    against an over-eager fail-closed implementation that would
    incorrectly fail-close *all* requests during an outage.

    We use an arbitrary token literal that does not start with ``sk_``;
    the middleware sees it is not an API-key plaintext and skips the
    counter path before any Redis call would happen, so even with the
    Redis eval patched to raise, the request is forwarded to the
    handler. The handler will return 401 because the token is not a
    valid JWT, but the load-bearing assertion is that the limiter did
    not short-circuit with 503.
    """
    _patch_redis_eval(monkeypatch, RedisConnectionError)

    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-real-jwt-but-not-sk-either"},
    )
    assert response.status_code != 503, (
        f"non-API-key request was incorrectly fail-closed by the limiter: "
        f"{response.status_code} {response.text!r}"
    )


@pytest.mark.asyncio
async def test_p18_unauthenticated_request_bypasses_limiter_unaffected(
    async_client, monkeypatch
) -> None:
    """Anonymous requests bypass the limiter and survive a Redis outage.

    A bare request with no credentials has no API-key plaintext for the
    middleware to anchor on, so it must skip the counter path
    altogether. A Redis outage must not propagate as 503 to anonymous
    callers; their requests should reach the route handler (which will
    typically return 401 for protected endpoints, or the route content
    for public endpoints).
    """
    _patch_redis_eval(monkeypatch, RedisConnectionError)

    response = await async_client.get("/api/v1/auth/me")
    assert response.status_code != 503, (
        f"anonymous request was incorrectly fail-closed by the limiter: "
        f"{response.status_code} {response.text!r}"
    )

"""Property test P19 (rate-limit clause): Audit emission for rate-limit verbs.

Per design.md §Property 19 and the audit verb table at design §Component 10,
the per-API-key rate limiter middleware must emit exactly one audit row per
terminal transition under the two verbs it owns:

* ``rate_limit.rejected`` — written on every 429 quota-exceeded response,
  with ``resource_type='api_key'`` and the offending key's prefix in
  ``details``.
* ``rate_limiter.backend_unavailable`` — written on every 503 fail-closed
  response triggered by a Redis ``ConnectionError`` / timeout, with
  ``resource_type='system'``.

Property 18 (covered separately by ``test_property_rate_limit_fail_closed``)
already establishes the broader fail-closed contract — that the route
handler is not invoked and the body has the documented shape. Here we
focus narrowly on the audit-emission cardinality and the verb-level
metadata that Requirement 7.5 calls out: every denial yields exactly one
matching audit row, and every outage yields exactly one matching audit row.

Strategy
--------

Two Hypothesis-driven properties, both seeded with ``max_examples=20`` per
the task brief (the denial-path test commits real Redis state across
examples so we keep the example count small and prefix-isolate each
example):

* **Denial path** — Hypothesis varies the request route and the API-key
  plaintext per example. We override the platform per-minute quota to
  ``N=2`` via ``app.config.settings``, then issue ``N+1=3`` requests with
  the same key. The first ``N`` are within quota and produce no audit
  rows; the ``(N+1)``-th request is the denied call. The property asserts
  exactly one ``rate_limit.rejected`` audit row whose ``resource_type`` is
  ``api_key`` and whose ``details`` carries the key prefix.
* **Outage path** — Hypothesis varies the Redis exception class
  (``ConnectionError`` / ``TimeoutError``) and the request route. We
  monkeypatch ``redis.asyncio.client.Redis.eval`` to raise; the middleware
  takes its fail-closed branch and must emit exactly one
  ``rate_limiter.backend_unavailable`` audit row whose ``resource_type`` is
  ``system``. This duplicates the spirit of P18 but with explicit
  cardinality assertions on the verb-level audit contract.

Resource scoping
----------------

Hypothesis examples in a single test invocation share the same Postgres
database because the middleware audit emitter commits independently of
the conftest's per-test session. We therefore wipe ``audit_logs`` at the
start of every example so the per-example "exactly one row" assertion is
scoped to a single request (denial path) or a single 503 (outage path).
The dedicated ``audit_engine`` fixture mirrors the one used in P18.

Validates: Requirements 7.5
"""

# Feature: api-platform-export, Property 19 (rate-limit clause): Audit emission

from __future__ import annotations

import string
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


# A small set of read-only public routes. The middleware applies before
# the router resolves the path, so the routes need not exist for the
# property to hold — but using real routes makes the test resemble a
# production request and exercises the audit row's ``method`` and
# ``path`` payload across multiple values.
_ROUTES: List[Tuple[str, str]] = [
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/api-keys/"),
    ("GET", "/api/v1/exports/"),
]


# Both Redis exception classes route to the same fail-closed branch. We
# sample over the pair so the property covers the network-unreachable
# and socket-timeout cases.
_REDIS_EXCEPTIONS = (RedisConnectionError, RedisTimeoutError)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def audit_engine():
    """Provide a dedicated engine for reading and truncating ``audit_logs``.

    The middleware emits its audit rows through a fresh
    ``app.database.async_session()`` and commits independently of the
    conftest's per-test ``db_session`` (which wraps the test in a
    rollback-at-teardown transaction). Reading through the per-test
    session would therefore miss the committed row, and writing to it
    would close the wrapping transaction. A dedicated engine sidesteps
    both problems and avoids any coupling to ``app.database.engine``,
    which the conftest disposes between tests.

    Function-scoped because asyncpg connections are bound to the event
    loop on which they were created; pytest-asyncio creates one loop
    per test by default.
    """
    test_db_url = app_settings.database_url.replace(
        "survey_db", "survey_test_db"
    )
    engine = create_async_engine(test_db_url, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def small_minute_quota(monkeypatch):
    """Override the platform per-minute quota to ``2`` for the duration of a test.

    The middleware reads ``settings.rate_limit_default_per_minute`` on
    every request rather than caching the value. Patching the attribute
    on the settings singleton therefore shrinks the quota for every
    request the middleware processes during this test, regardless of
    which key it sees. The hour and day quotas are also lowered (to
    very generous values that still exceed the small denial-path
    request bursts we send) so the deny path is unambiguously triggered
    by the minute window rather than by a cross-window race.

    Pytest's ``monkeypatch`` undoes the override at teardown so other
    tests see the original defaults.
    """
    monkeypatch.setattr(app_settings, "rate_limit_default_per_minute", 2)
    # Keep hour and day generously high so they cannot trip first.
    monkeypatch.setattr(app_settings, "rate_limit_default_per_hour", 10_000)
    monkeypatch.setattr(app_settings, "rate_limit_default_per_day", 100_000)
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _truncate_audit_logs(engine) -> None:
    """Delete every row from ``audit_logs`` using the dedicated engine.

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

    Patching ``eval`` on the class object makes every call raise the
    desired exception, regardless of whether the middleware has built
    its lazy client yet. Pytest's ``monkeypatch`` undoes the patch at
    teardown even if the test raises.
    """

    async def _raise(self, *args, **kwargs):
        raise exc_cls("simulated Redis outage")

    monkeypatch.setattr(aioredis.Redis, "eval", _raise, raising=True)


def _make_api_key(suffix: str) -> str:
    """Build an ``sk_``-prefixed plaintext whose 11-char prefix encodes ``suffix``.

    The middleware uses the first 11 characters of the plaintext as
    the rate-limit identity, so the test must ensure (a) the value is
    long enough that ``token[:11]`` is well-defined, and (b) the
    11-character prefix is unique per Hypothesis example so successive
    examples never share Redis counter state. We pack 8 characters of
    ``suffix`` into positions 3..10 of the plaintext (after the
    mandatory ``sk_`` prefix the middleware uses to recognize an
    API-key request), padding with ``z`` if the suffix is shorter than
    8 characters. The resulting 11-character prefix is fully
    determined by ``suffix``, so distinct suffixes produce distinct
    Redis counter buckets.
    """
    payload = (suffix + "z" * 8)[:8]
    plain = f"sk_{payload}-{uuid.uuid4().hex}"
    assert plain.startswith("sk_")
    assert len(plain) >= 11
    return plain


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


_ROUTE_STRATEGY = st.sampled_from(_ROUTES)
_REDIS_EXCEPTION_STRATEGY = st.sampled_from(_REDIS_EXCEPTIONS)

# Distinct API-key prefixes per example. Lowercase letters and digits
# keep the generated suffix narrow enough that Hypothesis shrinks
# towards small alphabets, and ``min_size=4`` ensures the resulting
# 11-character prefix is unique with high probability across the 20
# generated examples.
_KEY_SUFFIX_STRATEGY = st.text(
    alphabet=string.ascii_lowercase + string.digits,
    min_size=4,
    max_size=12,
)


# ---------------------------------------------------------------------------
# Property — denial path
# ---------------------------------------------------------------------------


# Feature: api-platform-export, Property 19 (rate-limit clause)
# Validates: Requirements 7.5
@pytest.mark.asyncio
@given(
    route=_ROUTE_STRATEGY,
    key_suffix=_KEY_SUFFIX_STRATEGY,
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p19_rate_limit_denial_emits_exactly_one_audit_row(
    route: Tuple[str, str],
    key_suffix: str,
    async_client,
    audit_engine,
    small_minute_quota,
) -> None:
    """A 429 quota-exceeded response emits exactly one ``rate_limit.rejected`` row.

    With the per-minute quota lowered to ``N=2`` we issue three requests
    against the same API-key prefix on the chosen route. The first two
    are within quota and produce no rate-limit audit rows; the third is
    denied 429 and must produce exactly one ``rate_limit.rejected``
    audit row whose ``resource_type`` is ``api_key`` and whose
    ``details`` carries the key prefix and the ``minute`` window label.
    """
    # Wipe rows from prior examples so the per-example uniqueness
    # assertion below is scoped to this denial.
    await _truncate_audit_logs(audit_engine)

    method, path = route
    plaintext = _make_api_key(f"p19a{key_suffix}{uuid.uuid4().hex[:6]}")
    expected_prefix = plaintext[:11]
    headers = {"X-API-Key": plaintext}

    # First N=2 requests — within quota, no rate-limit audit row.
    for _ in range(2):
        if method == "GET":
            resp = await async_client.get(path, headers=headers)
        else:  # pragma: no cover — strategy is closed under {"GET"}
            raise AssertionError(f"unexpected method: {method!r}")
        assert resp.status_code != 429, (
            f"unexpected early 429 on within-quota request: "
            f"{resp.status_code} {resp.text!r}"
        )

    # Sanity check: still no ``rate_limit.rejected`` row.
    pre_rows = await _read_audit_rows_by_action(audit_engine, "rate_limit.rejected")
    assert pre_rows == [], (
        f"unexpected rate_limit.rejected rows before quota exhaustion: "
        f"{[(r.action, r.details) for r in pre_rows]!r}"
    )

    # Third request — over quota, must be denied 429.
    if method == "GET":
        denied = await async_client.get(path, headers=headers)
    else:  # pragma: no cover — strategy is closed under {"GET"}
        raise AssertionError(f"unexpected method: {method!r}")

    assert denied.status_code == 429, (
        f"expected 429 on (N+1)-th request, got {denied.status_code}: "
        f"{denied.text!r}"
    )

    # Exactly one ``rate_limit.rejected`` audit row appended.
    rows = await _read_audit_rows_by_action(audit_engine, "rate_limit.rejected")
    assert len(rows) == 1, (
        f"expected exactly one rate_limit.rejected row, got {len(rows)}: "
        f"{[(r.action, r.details) for r in rows]!r}"
    )
    audit_row = rows[0]

    # Verb-level metadata per design §Component 10 audit verb table.
    assert audit_row.resource_type == "api_key", (
        f"unexpected resource_type: {audit_row.resource_type!r}"
    )
    assert audit_row.details is not None
    assert audit_row.details.get("key_prefix") == expected_prefix, (
        f"unexpected key_prefix in details: {audit_row.details!r}"
    )
    # The middleware records which window tripped; the minute window
    # is the only one we shrank, so it must be the one that fired.
    assert audit_row.details.get("window") == "minute", (
        f"unexpected exceeded window: {audit_row.details!r}"
    )
    assert audit_row.details.get("method") == method
    assert audit_row.details.get("path") == path


# ---------------------------------------------------------------------------
# Property — outage path
# ---------------------------------------------------------------------------


# Feature: api-platform-export, Property 19 (rate-limit clause)
# Validates: Requirements 7.5
@pytest.mark.asyncio
@given(
    exc_cls=_REDIS_EXCEPTION_STRATEGY,
    route=_ROUTE_STRATEGY,
    key_suffix=_KEY_SUFFIX_STRATEGY,
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p19_rate_limit_outage_emits_exactly_one_audit_row(
    exc_cls: type,
    route: Tuple[str, str],
    key_suffix: str,
    async_client,
    audit_engine,
    monkeypatch,
) -> None:
    """A 503 fail-closed response emits exactly one ``rate_limiter.backend_unavailable`` row.

    For every combination of Redis exception class, route, and API-key
    suffix, an API-key request must trigger the middleware's fail-closed
    branch and append exactly one
    ``rate_limiter.backend_unavailable`` audit row whose
    ``resource_type`` is ``system`` and whose ``details`` carries the
    request method and path.
    """
    await _truncate_audit_logs(audit_engine)

    method, path = route
    plaintext = _make_api_key(f"p19b{key_suffix}{uuid.uuid4().hex[:6]}")
    headers = {"X-API-Key": plaintext}

    _patch_redis_eval(monkeypatch, exc_cls)

    if method == "GET":
        resp = await async_client.get(path, headers=headers)
    else:  # pragma: no cover — strategy is closed under {"GET"}
        raise AssertionError(f"unexpected method: {method!r}")

    assert resp.status_code == 503, (
        f"expected 503 fail-closed, got {resp.status_code}: {resp.text!r}"
    )
    assert resp.json() == {"error": "rate_limiter.backend_unavailable"}

    rows = await _read_audit_rows_by_action(
        audit_engine, "rate_limiter.backend_unavailable"
    )
    assert len(rows) == 1, (
        f"expected exactly one rate_limiter.backend_unavailable row, "
        f"got {len(rows)}: {[(r.action, r.details) for r in rows]!r}"
    )
    audit_row = rows[0]
    assert audit_row.resource_type == "system", (
        f"unexpected resource_type: {audit_row.resource_type!r}"
    )
    assert audit_row.details is not None
    assert audit_row.details.get("method") == method
    assert audit_row.details.get("path") == path


# ---------------------------------------------------------------------------
# Anchor example tests
# ---------------------------------------------------------------------------
#
# Pin two specific failure modes Hypothesis would otherwise have to
# rediscover on every run. These also document the contract in plain
# pytest-friendly form.


@pytest.mark.asyncio
async def test_p19_rate_limit_denial_anchor(
    async_client, audit_engine, small_minute_quota
) -> None:
    """Anchor: a single key over a quota of 2 produces one rejected audit row."""
    await _truncate_audit_logs(audit_engine)

    plaintext = _make_api_key(f"anchor{uuid.uuid4().hex[:8]}")
    headers = {"X-API-Key": plaintext}

    for _ in range(2):
        resp = await async_client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code != 429

    denied = await async_client.get("/api/v1/auth/me", headers=headers)
    assert denied.status_code == 429
    assert "Retry-After" in denied.headers

    rows = await _read_audit_rows_by_action(audit_engine, "rate_limit.rejected")
    assert len(rows) == 1
    assert rows[0].resource_type == "api_key"
    assert rows[0].details["key_prefix"] == plaintext[:11]


@pytest.mark.asyncio
async def test_p19_rate_limit_outage_anchor(
    async_client, audit_engine, monkeypatch
) -> None:
    """Anchor: a single Redis ConnectionError yields one outage audit row."""
    await _truncate_audit_logs(audit_engine)

    _patch_redis_eval(monkeypatch, RedisConnectionError)

    plaintext = _make_api_key(f"outage{uuid.uuid4().hex[:8]}")
    resp = await async_client.get(
        "/api/v1/auth/me", headers={"X-API-Key": plaintext}
    )
    assert resp.status_code == 503

    rows = await _read_audit_rows_by_action(
        audit_engine, "rate_limiter.backend_unavailable"
    )
    assert len(rows) == 1
    assert rows[0].resource_type == "system"

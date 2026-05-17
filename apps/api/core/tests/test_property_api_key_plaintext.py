"""Property test P1 (API key clause): plaintext API key is returned exactly-once.

Per design §Property 1 (Requirements 2.1, 2.3, 2.8), the plaintext value
of an API key (``sk_<env>_<24 url-safe characters>``) must appear
**exactly once** — in the body of the response that issued or rotated
it — and **nowhere else**. Concretely:

* The create response (``POST /api/v1/api-keys/``) returns the
  ``plaintext`` field once.
* The rotate response (``POST /api/v1/api-keys/{key_id}/rotate``)
  returns a fresh ``plaintext`` field once.
* No other endpoint may surface either secret. The list endpoint must
  omit the plaintext, exposing only the safe ``key_prefix`` (first 11
  chars).
* The on-disk persistence surfaces — ``api_keys.key_hash`` (SHA-256
  hex of the plaintext) and ``audit_logs.details`` (JSONB) — must not
  contain the full plaintext bytes.
* The ``api_keys.key_prefix`` column legitimately stores the first 11
  characters of the plaintext (by design, for fast O(1) auth lookup);
  the substring scan therefore looks for the *full* 32-character
  plaintext, which structurally cannot fit inside an 11-character
  column. Scanning for the full plaintext catches the failure mode
  this property cares about: a regression where a longer plaintext
  prefix or the full secret leaks into a non-plaintext column.

The Hypothesis strategy generates a small sequence of operations per
example: 1-3 keys, each with 0-2 rotations. Every plaintext returned
by a create or rotate call is collected, and that set is checked for
membership against every byte source listed above.

Fixture pattern:
    The api_keys routes call ``await db.commit()`` after every
    transition, which is incompatible with the conftest-wide
    ``db_session`` fixture (it wraps the session in a
    ``session.begin()`` context that rolls back at teardown — once a
    route commits, the outer context manager rejects the rollback).
    This module declares its own ``apk_p1_session_factory`` and
    ``apk_p1_client`` fixtures (renamed from the webhook sibling's
    ``p1_*`` prefix to avoid pytest fixture-name collision when the
    two property tests run in the same session). The pattern mirrors
    ``test_property_webhook_secret_plaintext_exactly_once.py`` — same
    property, sibling clause.

This is the **API key clause** of Property 1. The webhook clause is
covered by ``test_property_webhook_secret_plaintext_exactly_once.py``.

# Feature: api-platform-export, Property 1: Plaintext credential exposure is exactly-once
# Validates: Requirements 2.1, 2.3, 2.8
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings, strategies as st
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import create_access_token, hash_password
from app.database import get_db
from app.main import app
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.user import User


# ── Strategies ────────────────────────────────────────────────────────

# Each example is a small list of "actions". An action is a non-negative
# integer denoting how many rotations to perform on a freshly created
# API key. Bounding each operation to a tight range keeps the
# 100-example run cheap on a real Postgres while still exercising the
# create-then-rotate compositions where ``key_prefix`` and ``key_hash``
# are mutated in place.
_ROTATION_COUNT = st.integers(min_value=0, max_value=2)

_PLAN = st.lists(
    _ROTATION_COUNT,
    min_size=1,
    max_size=3,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def apk_p1_session_factory(test_engine) -> async_sessionmaker:
    """Session factory bound to the function-scoped test engine.

    Each call yields a fresh :class:`AsyncSession` with no outer
    ``session.begin()`` wrapper, so the route's ``await db.commit()``
    succeeds without invalidating later operations across Hypothesis
    examples. ``expire_on_commit=False`` matches the production
    factory so attribute access on rows after commit behaves the same
    way the route does.

    The fixture is named ``apk_p1_*`` (not ``p1_*``) to avoid pytest
    fixture-name collision with the webhook sibling at
    ``test_property_webhook_secret_plaintext_exactly_once.py``.
    """
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest_asyncio.fixture
async def apk_p1_client(
    apk_p1_session_factory: async_sessionmaker,
) -> AsyncIterator[AsyncClient]:
    """HTTP client that injects a fresh route session per request.

    Replaces the conftest-wide ``async_client`` fixture for this
    property test only. The dependency override returns a brand-new
    session for each ``Depends(get_db)`` resolution, so the route's
    ``await db.commit()`` is the natural commit-and-close pattern
    rather than fighting the conftest's transaction wrapper.
    """

    async def _fresh_route_db() -> AsyncIterator[AsyncSession]:
        async with apk_p1_session_factory() as s:
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


# ── Helpers ───────────────────────────────────────────────────────────


async def _make_owner(
    apk_p1_session_factory: async_sessionmaker,
) -> Tuple[str, str]:
    """Insert a fresh owner user and return ``(user_id, JWT bearer token)``.

    A unique email per call keeps owners from colliding across
    Hypothesis examples that share the function-scoped factory. The
    JWT is required because every API-key management route is
    JWT-only (Req 8 AC5: API keys must never grant the ability to
    manage other API keys).

    Args:
        apk_p1_session_factory: The session factory yielded by the
            module's ``apk_p1_session_factory`` fixture.

    Returns:
        A ``(user_id, jwt_bearer_token)`` pair.
    """
    async with apk_p1_session_factory() as s:
        user = User(
            id=str(uuid.uuid4()),
            email=f"p1-apikey-{uuid.uuid4().hex[:12]}@example.com",
            hashed_password=hash_password("Test1234!"),
            display_name="P1 API Key Owner",
        )
        s.add(user)
        await s.commit()
        user_id = user.id
    return user_id, create_access_token(user_id)


async def _create_api_key(
    client: AsyncClient, headers: dict, label: str
) -> Tuple[str, str]:
    """Hit ``POST /api/v1/api-keys/`` and return ``(key_id, plaintext)``.

    The route returns the plaintext exactly once; we capture it here
    so the assertion phase can scan every other surface for the same
    bytes. A minimal valid payload (single ``survey:read`` scope, no
    expiry, no rate-limit overrides) keeps validation edge cases out
    of the test scope.

    Args:
        client: The HTTP test client wired to the no-txn session.
        headers: ``Authorization: Bearer <jwt>`` headers for the owner.
        label: A unique ``name`` for the key — uniqueness is not a
            constraint, but using distinct names eases debugging when
            Hypothesis shrinks a failure.

    Returns:
        A ``(key_id, full_plaintext)`` pair.
    """
    resp = await client.post(
        "/api/v1/api-keys/",
        headers=headers,
        json={
            "name": label,
            "scopes": ["survey:read"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    plaintext = body["plaintext"]
    assert isinstance(plaintext, str) and plaintext, (
        "create response must surface a non-empty plaintext string"
    )
    # The plaintext format is ``sk_<env>_<24 chars>`` so the full
    # secret is at least 11 characters longer than ``key_prefix``.
    # That length differential is what makes the substring scan over
    # ``key_prefix`` a meaningful check rather than a tautology.
    assert plaintext.startswith("sk_live_"), (
        f"plaintext must use the live env tag, got {plaintext!r}"
    )
    assert len(plaintext) > len(body["key_prefix"]), (
        f"plaintext ({len(plaintext)} chars) must be longer than "
        f"key_prefix ({len(body['key_prefix'])} chars) for the "
        f"substring scan to be meaningful"
    )
    return body["id"], plaintext


async def _rotate_api_key(
    client: AsyncClient, headers: dict, key_id: str
) -> str:
    """Hit ``POST /api/v1/api-keys/{key_id}/rotate``; return new plaintext.

    Each rotation must surface a fresh plaintext in the response body.
    The previous plaintext is no longer recoverable through any
    surface — that's the load-bearing claim of the rotate clause of
    Property 1, and we add the new plaintext to the collected set so
    the scan phase covers all rotations in the sequence.

    Args:
        client: The HTTP test client wired to the no-txn session.
        headers: Owner's bearer-token headers.
        key_id: The id of the key to rotate.

    Returns:
        The new plaintext returned by the rotate response.
    """
    resp = await client.post(
        f"/api/v1/api-keys/{key_id}/rotate",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    plaintext = body["plaintext"]
    assert isinstance(plaintext, str) and plaintext, (
        "rotate response must surface a non-empty plaintext string"
    )
    assert plaintext.startswith("sk_live_"), (
        f"rotated plaintext must use the live env tag, got {plaintext!r}"
    )
    return plaintext


def _scan_for_secret(haystack: Any, secrets: Set[str]) -> List[str]:
    """Return any secret present anywhere inside a JSON-serializable value.

    The check serializes the haystack through ``json.dumps`` and uses
    a substring test. Substring is the right semantics here: we want
    to catch a plaintext leak whether it sits in a response field, a
    nested dict, a list element, a stringified repr inside a log
    line, or interpolated into another value. Each plaintext is a
    32-character ``sk_<env>_``-prefixed token, so false positives
    from incidental coincidence are vanishingly unlikely (the
    24-character body is drawn from a CSPRNG, ~144 bits of entropy).

    Args:
        haystack: A JSON-serializable Python value.
        secrets: The set of plaintext API keys to check for.

    Returns:
        List of plaintexts that were found in ``haystack``. Empty list
        means the haystack is clean.
    """
    if not secrets:
        return []
    blob = json.dumps(haystack, default=str, ensure_ascii=False)
    return [s for s in secrets if s in blob]


def _scan_string_for_secret(
    text: Optional[str], secrets: Set[str]
) -> List[str]:
    """Substring scan over a raw string column value.

    Used for the database column scan where the column holds either a
    single string value or ``None``. Mirrors :func:`_scan_for_secret`
    but skips the JSON serialization step.

    Args:
        text: The raw string column value, or ``None``.
        secrets: The set of plaintext API keys to check for.

    Returns:
        List of plaintexts that were found in ``text``. Empty list
        means the column is clean.
    """
    if text is None or not secrets:
        return []
    if not isinstance(text, str):
        return []
    return [s for s in secrets if s in text]


async def _query_api_keys(
    apk_p1_session_factory: async_sessionmaker, key_ids: List[str]
) -> List[ApiKey]:
    """Direct ``SELECT`` of the ``api_keys`` rows for the given ids.

    Args:
        apk_p1_session_factory: The session factory yielded by the
            module fixture.
        key_ids: The list of api_keys.id values to fetch.

    Returns:
        A list of :class:`ApiKey` ORM rows; order is not guaranteed.
    """
    if not key_ids:
        return []
    async with apk_p1_session_factory() as s:
        result = await s.execute(
            select(ApiKey).where(ApiKey.id.in_(key_ids))
        )
        return list(result.scalars().all())


async def _query_audit_rows(
    apk_p1_session_factory: async_sessionmaker, key_ids: List[str]
) -> List[AuditLog]:
    """Direct ``SELECT`` of audit rows whose ``resource_id`` is in ``key_ids``.

    Scoping the read by ``resource_id`` keeps the scan bounded to the
    keys this Hypothesis example created, so audit rows from earlier
    examples in the same test invocation are ignored.

    Args:
        apk_p1_session_factory: The session factory yielded by the
            module fixture.
        key_ids: The list of api_keys.id values to scope by.

    Returns:
        A list of :class:`AuditLog` ORM rows; order is not guaranteed.
    """
    if not key_ids:
        return []
    async with apk_p1_session_factory() as s:
        result = await s.execute(
            select(AuditLog).where(AuditLog.resource_id.in_(key_ids))
        )
        return list(result.scalars().all())


# ── The property test ────────────────────────────────────────────────


# Feature: api-platform-export, Property 1: Plaintext credential exposure is exactly-once
# Validates: Requirements 2.1, 2.3, 2.8
@pytest.mark.asyncio
@given(plan=_PLAN)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p1_api_key_plaintext_exactly_once(
    apk_p1_client: AsyncClient,
    apk_p1_session_factory: async_sessionmaker,
    plan: List[int],
) -> None:
    """The plaintext API key never appears outside the issuing response.

    Sub-invariants asserted in lock-step:

    * Every ``POST /api/v1/api-keys/`` and every
      ``POST /{key_id}/rotate`` response carries a non-empty
      ``plaintext`` string. This is the *issuance* half of "exactly
      once": the plaintext is surfaced exactly when the caller asked
      for it.
    * Every rotation yields a plaintext distinct from every secret
      previously issued in the example. Reusing a plaintext would
      make the "exactly once across rotations" claim vacuous and is
      forbidden by the CSPRNG guarantee in
      :func:`app.core.api_key_secret.generate_plaintext`.
    * The ``GET /api/v1/api-keys/`` list response carries no
      plaintext from any key, regardless of whether it was just
      created or had its secret rotated. Listing must never reveal a
      full secret; only the safe ``key_prefix`` (first 11 chars) is
      surfaced.
    * Direct ``SELECT`` on ``api_keys.key_hash`` for every key
      created in this example yields **no** plaintext bytes from the
      collected set. The hash column stores a 64-character SHA-256
      hex digest of the plaintext, which structurally cannot contain
      the plaintext (different alphabet, different length); the
      assertion still runs as a defence in depth against a
      regression where the column starts holding plaintext directly.
    * Direct ``SELECT`` on ``api_keys.key_prefix`` yields no full
      plaintext. The column legitimately stores the first 11
      characters of the plaintext (by design — see the model
      docstring), so the substring scan deliberately looks for the
      *full* plaintext, which is 32 characters and cannot fit inside
      an 11-character column. The scan therefore catches a
      regression where the column accidentally widens to hold the
      full secret.
    * Direct ``SELECT`` on ``audit_logs`` rows owned by this
      example's key set yields no plaintext anywhere inside any
      ``details`` JSONB column. The audit details may carry the key
      id, name, and scopes, but never the secret.

    Validates: Requirements 2.1, 2.3, 2.8.
    """
    user_id, token = await _make_owner(apk_p1_session_factory)
    headers = {"Authorization": f"Bearer {token}"}

    secrets: Set[str] = set()
    key_ids: List[str] = []

    # --- Phase 1: drive the create-and-rotate sequence ----------------
    for plan_idx, rotation_count in enumerate(plan):
        label = f"p1-apikey-{plan_idx}-{uuid.uuid4().hex[:6]}"
        key_id, plaintext = await _create_api_key(
            apk_p1_client, headers, label
        )
        key_ids.append(key_id)
        assert plaintext not in secrets, (
            "create returned a plaintext that was already issued; "
            "secrets must be cryptographically fresh"
        )
        secrets.add(plaintext)

        for _ in range(rotation_count):
            new_plaintext = await _rotate_api_key(
                apk_p1_client, headers, key_id
            )
            assert new_plaintext not in secrets, (
                "rotate returned a plaintext that was already issued; "
                "secrets must be cryptographically fresh"
            )
            secrets.add(new_plaintext)

    # --- Phase 2: scan the read endpoints -----------------------------
    list_resp = await apk_p1_client.get(
        "/api/v1/api-keys/", headers=headers
    )
    assert list_resp.status_code == 200, list_resp.text
    list_body = list_resp.json()
    leaked_in_list = _scan_for_secret(list_body, secrets)
    assert not leaked_in_list, (
        f"plaintext API key leaked into list response: "
        f"{leaked_in_list!r}"
    )

    # Belt-and-braces: confirm the list shape never carries a
    # ``plaintext`` field at all. The ``ApiKeyOut`` schema omits it
    # by construction; this guards against a regression where the
    # router accidentally serializes via ``ApiKeyCreateOut`` on the
    # list path.
    assert isinstance(list_body, list), (
        f"list response must be a list, got {type(list_body).__name__}"
    )
    for entry in list_body:
        assert "plaintext" not in entry, (
            f"list response entry must omit plaintext field: "
            f"{entry!r}"
        )

    # --- Phase 3: scan the persistence surfaces -----------------------
    key_rows = await _query_api_keys(apk_p1_session_factory, key_ids)
    assert len(key_rows) == len(key_ids), (
        f"expected {len(key_ids)} api_keys rows, got {len(key_rows)}"
    )

    for row in key_rows:
        leaked_in_hash = _scan_string_for_secret(row.key_hash, secrets)
        assert not leaked_in_hash, (
            f"plaintext API key found in api_keys.key_hash for key "
            f"{row.id}: {leaked_in_hash!r}"
        )
        # ``key_prefix`` is an 11-character column that legitimately
        # stores the first 11 characters of the plaintext; we scan
        # for the *full* plaintext here, which structurally cannot
        # fit. A substring match would mean the column grew to hold
        # the full secret — a real leak.
        leaked_in_prefix = _scan_string_for_secret(
            row.key_prefix, secrets
        )
        assert not leaked_in_prefix, (
            f"full plaintext API key found in api_keys.key_prefix "
            f"for key {row.id}: {leaked_in_prefix!r}"
        )

    audit_rows = await _query_audit_rows(
        apk_p1_session_factory, key_ids
    )
    for audit_row in audit_rows:
        details: Dict[str, Any] = audit_row.details or {}
        leaked_in_audit = _scan_for_secret(details, secrets)
        assert not leaked_in_audit, (
            f"plaintext API key found in audit_logs.details for "
            f"audit row {audit_row.id} (action={audit_row.action!r}, "
            f"resource_id={audit_row.resource_id!r}): "
            f"{leaked_in_audit!r}"
        )

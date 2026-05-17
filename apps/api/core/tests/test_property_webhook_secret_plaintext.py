"""Property test P1 (webhook portion): plaintext signing secret is returned exactly-once.

Per design §Property 1 (Requirements 4.2, 4.10), the plaintext value of
a webhook subscription's signing secret must appear **exactly once** —
in the body of the response that issued or rotated it — and **nowhere
else**. Concretely:

* The create response (``POST /api/v1/webhooks/``) returns the
  ``signing_secret`` field once.
* The rotate-secret response
  (``POST /api/v1/webhooks/{sub_id}/rotate-secret``) returns a fresh
  ``signing_secret`` field once.
* No other endpoint may surface either secret. The list endpoint, the
  patch response, and the deliveries-history endpoint must omit the
  plaintext.
* The on-disk persistence surfaces — ``webhook_subscriptions``
  ``signing_secret_ciphertext``, ``webhook_subscriptions``
  ``previous_secret_ciphertext``, and the ``audit_logs.details``
  JSONB — must store at most a non-recoverable derivative (Fernet
  ciphertext or ``None``), not the plaintext bytes themselves.

The Hypothesis strategy generates a small sequence of operations per
example: 1-3 subscriptions, each with 0-2 secret rotations. Every
plaintext returned by a create or rotate-secret call goes into a
collected set, and that set is then checked for membership against
every byte source listed above.

Fixture pattern:
    The webhook routes call ``await db.commit()`` after every
    transition, which is incompatible with the conftest-wide
    ``db_session`` fixture (it wraps the session in a
    ``session.begin()`` context that rolls back at teardown — once a
    route commits, the outer context manager rejects the rollback).
    This module therefore declares its own ``p1_session_factory`` and
    ``p1_client`` fixtures that hand the route a brand-new session per
    request and let the route's commits land naturally. The pattern
    mirrors the one introduced by the Property 19 webhook test for the
    same root cause; see
    ``tests/test_property_webhook_subscription_audit_emission.py`` for
    the canonical example.

This is the **webhook clause** of Property 1. The API-key clause is
covered by the sub-task at 4.3 of the same spec.

# Feature: api-platform-export, Property 1: Plaintext credential exposure is exactly-once
# Validates: Requirements 4.2, 4.10
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Dict, List, Set, Tuple

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings, strategies as st
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import create_access_token, hash_password
from app.database import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.webhook_subscription import WebhookSubscription


# ── Strategies ────────────────────────────────────────────────────────

# Each example is a small list of "actions". An action is a non-negative
# integer denoting how many rotations to perform on a freshly created
# subscription. Bounding each operation to a tight range keeps the
# 100-example run cheap on a real Postgres while still exercising the
# create-then-rotate compositions where the
# ``previous_secret_ciphertext`` slot becomes interesting.
_ROTATION_COUNT = st.integers(min_value=0, max_value=2)

_PLAN = st.lists(
    _ROTATION_COUNT,
    min_size=1,
    max_size=3,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def p1_session_factory(test_engine) -> async_sessionmaker:
    """Session factory bound to the function-scoped test engine.

    Each call yields a fresh :class:`AsyncSession` with no outer
    ``session.begin()`` wrapper, so the route's ``await db.commit()``
    succeeds without invalidating later operations across Hypothesis
    examples. ``expire_on_commit=False`` matches the production
    factory so attribute access on rows after commit behaves the same
    way the route does.
    """
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest_asyncio.fixture
async def p1_client(
    p1_session_factory: async_sessionmaker,
) -> AsyncIterator[AsyncClient]:
    """HTTP client that injects a fresh route session per request.

    Replaces the conftest-wide ``async_client`` fixture for this
    property test only. The dependency override returns a brand-new
    session for each ``Depends(get_db)`` resolution, so the route's
    ``await db.commit()`` is the natural commit-and-close pattern
    rather than fighting the conftest's transaction wrapper.
    """

    async def _fresh_route_db() -> AsyncIterator[AsyncSession]:
        async with p1_session_factory() as s:
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
    p1_session_factory: async_sessionmaker,
) -> Tuple[str, str]:
    """Insert a fresh owner user and return ``(user_id, JWT bearer token)``.

    A unique email per call keeps owners from colliding across
    Hypothesis examples that share the function-scoped factory.
    """
    async with p1_session_factory() as s:
        user = User(
            email=f"p1-webhook-{uuid.uuid4().hex[:12]}@example.com",
            hashed_password=hash_password("Test1234!"),
            display_name="P1 Owner",
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        user_id = user.id
    return user_id, create_access_token(user_id)


async def _create_subscription(
    client: AsyncClient, headers: dict
) -> Tuple[str, str]:
    """Hit ``POST /api/v1/webhooks/`` and return ``(sub_id, plaintext)``.

    The route returns the plaintext exactly once; we capture it here
    so the assertion phase can scan every other surface for the same
    bytes. A minimal valid payload keeps validation edge cases out of
    the test scope.
    """
    resp = await client.post(
        "/api/v1/webhooks/",
        headers=headers,
        json={
            "target_url": "https://hooks.example.com/p1",
            "event_types": ["response.created"],
            "description": "P1 plaintext-exactly-once test",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    secret = body["signing_secret"]
    assert isinstance(secret, str) and secret, (
        "create response must surface a non-empty signing_secret string"
    )
    return body["id"], secret


async def _rotate_subscription(
    client: AsyncClient, headers: dict, sub_id: str
) -> str:
    """Hit ``POST /api/v1/webhooks/{sub_id}/rotate-secret``; return plaintext.

    Each rotation must surface a fresh plaintext secret in the response
    body. The previous plaintext is no longer available through any
    surface — that's the load-bearing claim of the rotate clause of
    Property 1, and we add the new plaintext to the collected set so
    the scan phase covers all rotations in the sequence.
    """
    resp = await client.post(
        f"/api/v1/webhooks/{sub_id}/rotate-secret",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    secret = body["signing_secret"]
    assert isinstance(secret, str) and secret, (
        "rotate-secret response must surface a non-empty "
        "signing_secret string"
    )
    return secret


def _scan_for_secret(haystack: Any, secrets: Set[str]) -> List[str]:
    """Return any secret present anywhere inside a JSON-serializable value.

    The check serializes the haystack through ``json.dumps`` and uses
    a simple substring test. Substring is the right semantics here:
    we want to catch a plaintext leak whether it sits in a response
    field, a nested dict, a list element, a stringified repr inside a
    log line, or interpolated into another value. Each plaintext is a
    ``whsec_``-prefixed token of about 38 characters, so false
    positives from incidental coincidence are vanishingly unlikely.

    Args:
        haystack: A JSON-serializable Python value.
        secrets: The set of plaintext signing secrets to check for.

    Returns:
        List of plaintexts that were found in ``haystack``. Empty list
        means the haystack is clean.
    """
    if not secrets:
        return []
    blob = json.dumps(haystack, default=str, ensure_ascii=False)
    return [s for s in secrets if s in blob]


def _scan_string_for_secret(text: Any, secrets: Set[str]) -> List[str]:
    """Substring scan over a raw string value (e.g. a DB column).

    Used for the database column scan where the column holds either
    a single string value or ``None``. Mirrors :func:`_scan_for_secret`
    but skips the JSON serialization step.
    """
    if text is None or not secrets:
        return []
    if not isinstance(text, str):
        return []
    return [s for s in secrets if s in text]


async def _query_subscriptions(
    p1_session_factory: async_sessionmaker, sub_ids: List[str]
) -> List[WebhookSubscription]:
    """Direct ``SELECT`` of the subscription rows for the given ids."""
    async with p1_session_factory() as s:
        result = await s.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.id.in_(sub_ids)
            )
        )
        return list(result.scalars().all())


async def _query_audit_rows(
    p1_session_factory: async_sessionmaker, sub_ids: List[str]
) -> List[AuditLog]:
    """Direct ``SELECT`` of audit rows whose resource_id is in ``sub_ids``."""
    async with p1_session_factory() as s:
        result = await s.execute(
            select(AuditLog).where(AuditLog.resource_id.in_(sub_ids))
        )
        return list(result.scalars().all())


# ── The property test ────────────────────────────────────────────────


# Feature: api-platform-export, Property 1: Plaintext credential exposure is exactly-once
# Validates: Requirements 4.2, 4.10
@pytest.mark.asyncio
@given(plan=_PLAN)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p1_webhook_signing_secret_plaintext_exactly_once(
    p1_client: AsyncClient,
    p1_session_factory: async_sessionmaker,
    plan: List[int],
) -> None:
    """The plaintext signing secret never appears outside the issuing response.

    Sub-invariants asserted in lock-step:

    * Every ``POST /api/v1/webhooks/`` and every
      ``POST /{sub_id}/rotate-secret`` response carries a non-empty
      ``signing_secret`` string. This is the *issuance* half of
      "exactly once": the plaintext is surfaced exactly when the
      caller asked for it.
    * Every rotation yields a plaintext distinct from every secret
      previously issued in the example. Reusing a plaintext would
      make the "exactly once across rotations" claim vacuous.
    * The ``GET /api/v1/webhooks/`` list response carries no plaintext
      from any subscription, regardless of whether it was just
      created or had its secret rotated. Listing must never reveal a
      secret.
    * The ``PATCH /api/v1/webhooks/{sub_id}`` response carries no
      plaintext. We trigger an actual update so the route's audit
      emission path runs; the patch body itself is a benign
      description change.
    * The ``GET /api/v1/webhooks/{sub_id}/deliveries`` response
      carries no plaintext. Delivery history is a separate read
      surface and must not echo a secret either.
    * Direct ``SELECT`` on
      ``webhook_subscriptions.signing_secret_ciphertext`` and
      ``webhook_subscriptions.previous_secret_ciphertext`` for every
      subscription created in this example yields **no** plaintext
      bytes from the collected set. The persistence surface stores a
      Fernet ciphertext or ``None``, never the plaintext.
    * Direct ``SELECT`` on ``audit_logs`` rows owned by this example's
      subscription set yields no plaintext anywhere inside any
      ``details`` JSONB column. The audit details may carry the
      subscription id, the target URL, and the changed-fields dict
      from updates, but never a secret.

    Validates: Requirements 4.2, 4.10.
    """
    user_id, token = await _make_owner(p1_session_factory)
    headers = {"Authorization": f"Bearer {token}"}

    secrets: Set[str] = set()
    sub_ids: List[str] = []

    # --- Phase 1: drive the create-and-rotate sequence ----------------
    for rotation_count in plan:
        sub_id, plaintext = await _create_subscription(p1_client, headers)
        sub_ids.append(sub_id)
        secrets.add(plaintext)

        for _ in range(rotation_count):
            new_plaintext = await _rotate_subscription(
                p1_client, headers, sub_id
            )
            assert new_plaintext not in secrets, (
                "rotate-secret returned a plaintext that was already "
                "issued; secrets must be cryptographically fresh"
            )
            secrets.add(new_plaintext)

    # --- Phase 2: scan the read endpoints -----------------------------
    list_resp = await p1_client.get("/api/v1/webhooks/", headers=headers)
    assert list_resp.status_code == 200, list_resp.text
    leaked_in_list = _scan_for_secret(list_resp.json(), secrets)
    assert not leaked_in_list, (
        f"plaintext signing secret leaked into list response: "
        f"{leaked_in_list!r}"
    )

    for sub_id in sub_ids:
        patch_resp = await p1_client.patch(
            f"/api/v1/webhooks/{sub_id}",
            headers=headers,
            json={"description": f"P1 patch for {sub_id[:8]}"},
        )
        assert patch_resp.status_code == 200, patch_resp.text
        leaked_in_patch = _scan_for_secret(patch_resp.json(), secrets)
        assert not leaked_in_patch, (
            f"plaintext signing secret leaked into patch response "
            f"for sub {sub_id}: {leaked_in_patch!r}"
        )

        deliveries_resp = await p1_client.get(
            f"/api/v1/webhooks/{sub_id}/deliveries",
            headers=headers,
        )
        assert deliveries_resp.status_code == 200, deliveries_resp.text
        leaked_in_deliveries = _scan_for_secret(
            deliveries_resp.json(), secrets
        )
        assert not leaked_in_deliveries, (
            f"plaintext signing secret leaked into deliveries "
            f"response for sub {sub_id}: {leaked_in_deliveries!r}"
        )

    # --- Phase 3: scan the persistence surfaces -----------------------
    sub_rows = await _query_subscriptions(p1_session_factory, sub_ids)
    assert len(sub_rows) == len(sub_ids), (
        f"expected {len(sub_ids)} webhook_subscriptions rows, got "
        f"{len(sub_rows)}"
    )

    for row in sub_rows:
        leaked_in_current = _scan_string_for_secret(
            row.signing_secret_ciphertext, secrets
        )
        assert not leaked_in_current, (
            f"plaintext signing secret found in "
            f"webhook_subscriptions.signing_secret_ciphertext for sub "
            f"{row.id}: {leaked_in_current!r}"
        )
        leaked_in_previous = _scan_string_for_secret(
            row.previous_secret_ciphertext, secrets
        )
        assert not leaked_in_previous, (
            f"plaintext signing secret found in "
            f"webhook_subscriptions.previous_secret_ciphertext for "
            f"sub {row.id}: {leaked_in_previous!r}"
        )

    audit_rows = await _query_audit_rows(p1_session_factory, sub_ids)
    for audit_row in audit_rows:
        details: Dict[str, Any] = audit_row.details or {}
        leaked_in_audit = _scan_for_secret(details, secrets)
        assert not leaked_in_audit, (
            f"plaintext signing secret found in audit_logs.details for "
            f"audit row {audit_row.id} (action={audit_row.action!r}, "
            f"resource_id={audit_row.resource_id!r}): "
            f"{leaked_in_audit!r}"
        )

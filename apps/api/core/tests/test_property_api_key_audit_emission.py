"""Property test P19 (api_key portion): Audit emission for terminal transitions.

Per design.md §Property 19, every state transition enumerated in the
audit verb table must append exactly one row to ``audit_logs`` whose
``action`` equals the corresponding verb, whose ``user_id`` equals the
acting user (the administrator for ``api_key.admin_revoke``), and
whose ``resource_type`` and ``resource_id`` reference the affected
entity.

This module validates the api_key portion of that property —
``api_key.create``, ``api_key.rotate``, ``api_key.revoke``, and
``api_key.admin_revoke`` — against the live FastAPI routes and the
real Postgres audit_logs table.

Strategy
--------

Hypothesis generates a small set of "keys" (1-3 per example) and a
short sequence of post-create operations per key (0-3 ops per key,
each drawn from ``{rotate, revoke, admin_revoke}``). For every
example we:

1. Provision a fresh owner user and a fresh admin user in the test
   DB (unique emails via ``uuid.uuid4()`` so concurrent or successive
   Hypothesis examples never collide).
2. Mint JWT access tokens for both, since every route under test is
   JWT-only per design §Component 2 and the admin force-revoke
   route additionally requires ``is_admin``.
3. Drive the create / rotate / revoke / admin-revoke HTTP routes
   through ``async_client`` per the generated plan.
4. Predict the multiset of ``(action, user_id, resource_type,
   resource_id)`` audit rows the run should have emitted by
   simulating the same plan against a reference state machine —
   idempotent revokes emit on the first call only, rotation on a
   revoked key returns 409 with no emission, etc.
5. Read back every ``audit_logs`` row whose ``resource_id`` matches
   one of the keys touched in this example and assert the multiset
   equals the prediction exactly. Scoping the read by
   ``resource_id`` lets the assertion ignore audit rows from prior
   Hypothesis examples — successive examples in a single Hypothesis
   run share the same Postgres database since the routes commit, so
   per-example resource scoping is the right isolation boundary.

Fixture rationale
-----------------

The conftest's stock ``db_session`` and ``async_client`` fixtures
wrap each test in ``async with session.begin()`` for rollback-style
isolation. That pattern is incompatible with the property tested
here: every route under test calls ``db.commit()`` (audit rows must
be durable, by design), and committing inside the wrapping context
manager closes the outer transaction so the next Hypothesis example
can no longer use the session. We therefore declare
``no_txn_db_session`` and ``no_txn_async_client`` in this module,
which build their session over the *same* test engine the conftest
uses but omit the wrapping ``session.begin()``. The conftest's
``test_engine`` recreates the schema from scratch at engine
construction (``Base.metadata.drop_all`` then ``create_all``), so
state from this test does not leak across test functions.

We additionally cap ``max_examples`` at 50 and suppress the
``function_scoped_fixture`` health-check per the task brief: the
test is DB-bound and issues several writes per example, and a 50-
example sample is sufficient for a small enumerated state machine.

Validates: Requirements 7.1, 9.4
"""

# Feature: api-platform-export, Property 19: Audit emission for terminal transitions

from __future__ import annotations

import uuid
from typing import Dict, List, Set, Tuple

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import create_access_token, hash_password
from app.database import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.user import User


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def no_txn_db_session(test_engine):
    """Yield an async session that allows route-side commits.

    Built on the same ``test_engine`` the conftest already exposes —
    so the database schema is the test database created and torn
    down by that fixture — but without the ``async with
    session.begin()`` wrapper the conftest's ``db_session`` fixture
    uses. Route handlers under test issue ``db.commit()`` directly,
    and committing inside ``session.begin()`` closes the outer
    context manager and breaks every subsequent Hypothesis example.
    Skipping the wrapper lets the session remain usable across
    examples; cleanup is handled by ``test_engine`` recreating the
    schema between test functions.
    """
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def no_txn_async_client(no_txn_db_session):
    """HTTP test client backed by ``no_txn_db_session``.

    Mirrors the conftest's ``async_client`` fixture but wires the
    dependency override to the commit-friendly session above so the
    routes under test can issue ``db.commit()`` without breaking
    successive Hypothesis examples.
    """
    app.dependency_overrides[get_db] = lambda: no_txn_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


# ── Strategy ──────────────────────────────────────────────────────────


_ACTION_KIND = st.sampled_from(("rotate", "revoke", "admin_revoke"))


@st.composite
def _key_plans(draw: st.DrawFn) -> List[List[str]]:
    """Generate 1-3 key plans, each a 0-3 element list of post-create ops.

    The outer list corresponds one-to-one to keys created at the start
    of the run; the inner list is the sequence of actions performed on
    that key after it exists. Hypothesis shrinks toward fewer keys and
    fewer ops, so a property failure typically reduces to a single
    key with a single action — which matches the failure mode the
    test brief calls out as the desired minimal counter-example.
    """
    n_keys = draw(st.integers(min_value=1, max_value=3))
    return [
        draw(st.lists(_ACTION_KIND, min_size=0, max_size=3))
        for _ in range(n_keys)
    ]


# ── Reference state machine ───────────────────────────────────────────


def _simulate(
    plans: List[List[str]],
    owner_id: str,
    admin_id: str,
    key_ids: List[str],
) -> List[Tuple[str, str, str, str]]:
    """Predict the audit rows the live run is expected to emit.

    Each tuple is ``(action_verb, user_id, resource_type, resource_id)``
    and is appended in the same order the live route handlers would
    write them. Order is not asserted by the property — the comparison
    is multiset equality — but emitting in causal order keeps the
    reference readable.

    The simulation tracks one ``revoked`` flag per key, which is set
    by both ``revoke`` and ``admin_revoke`` and consulted to decide
    whether a subsequent operation will actually mutate state and
    thus emit a row:

    * ``create`` always emits ``api_key.create`` with the owner as
      actor.
    * ``rotate`` on a non-revoked key emits ``api_key.rotate`` with
      the owner as actor; on a revoked key the route returns 409 and
      writes no audit row.
    * ``revoke`` is idempotent: it emits ``api_key.revoke`` with the
      owner as actor on the first call only; subsequent calls return
      the row unchanged with no audit row.
    * ``admin_revoke`` is idempotent: it emits
      ``api_key.admin_revoke`` with the *administrator* as actor on
      the first call only; subsequent calls return the row unchanged
      with no audit row.

    Args:
        plans: Per-key post-create operation plans.
        owner_id: User id of the owner that creates / rotates /
            self-revokes the keys.
        admin_id: User id of the administrator that issues
            force-revokes.
        key_ids: One key id per plan, in the same order. Captured at
            create time and reused so the simulation can attribute
            rows to the right resource.

    Returns:
        A list of ``(action, user_id, resource_type, resource_id)``
        tuples in causal order.
    """
    rows: List[Tuple[str, str, str, str]] = []
    for key_id, ops in zip(key_ids, plans):
        # Every plan starts with a create; emitted unconditionally.
        rows.append(("api_key.create", owner_id, "api_key", key_id))
        revoked = False
        for op in ops:
            if op == "rotate":
                if not revoked:
                    rows.append(("api_key.rotate", owner_id, "api_key", key_id))
                # On a revoked key the route returns 409, no row written.
            elif op == "revoke":
                if not revoked:
                    rows.append(("api_key.revoke", owner_id, "api_key", key_id))
                    revoked = True
            elif op == "admin_revoke":
                if not revoked:
                    rows.append(
                        ("api_key.admin_revoke", admin_id, "api_key", key_id)
                    )
                    revoked = True
            else:  # pragma: no cover — strategy is closed under the enum
                raise AssertionError(f"unexpected op kind: {op!r}")
    return rows


# ── Test helpers ──────────────────────────────────────────────────────


async def _make_user(db_session, *, is_admin: bool) -> User:
    """Insert a fresh User row with a unique email and return it.

    UUID-based emails keep successive Hypothesis examples isolated:
    rolling back the wrapping engine only happens at engine dispose,
    so any state committed by a route inside the test persists across
    examples. Unique emails ensure the email-uniqueness constraint
    never trips between examples.
    """
    email = f"p19-{uuid.uuid4()}@example.test"
    # Generate the id client-side so we can return a fully-populated
    # User without calling ``refresh`` afterwards. The route handlers
    # we drive next will commit through the same session, and a
    # ``refresh`` call sandwiched between two commits has been
    # observed to race with the asyncpg connection's transaction
    # state (``Could not refresh instance``).
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=hash_password("Test1234!"),
        display_name="P19 user",
        is_admin=is_admin,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _drive_plan(
    *,
    async_client,
    plans: List[List[str]],
    owner_token: str,
    admin_token: str,
) -> List[str]:
    """Execute the generated plan over HTTP and return the created key ids.

    Drives one create per plan plus the listed post-create ops. The
    routes are JWT-only per design §Component 2, so every call uses
    a Bearer token rather than the API-key path. The owner JWT is
    used for create / rotate / revoke; the admin JWT is used for the
    distinct ``api_key.admin_revoke`` verb.

    On rotate or revoke calls that are expected to be idempotent or
    blocked (a revoked key cannot be rotated; redundant revokes
    return the row unchanged), the route still responds successfully
    (or 409 for rotate-on-revoked) without writing a duplicate audit
    row. The reference state machine in :func:`_simulate` mirrors
    that behaviour so the property holds.
    """
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    key_ids: List[str] = []

    for plan_idx, ops in enumerate(plans):
        # Every plan begins with a create.
        create_resp = await async_client.post(
            "/api/v1/api-keys/",
            headers=owner_headers,
            json={
                "name": f"p19-key-{plan_idx}-{uuid.uuid4().hex[:6]}",
                "scopes": ["survey:read"],
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        key_id = create_resp.json()["id"]
        key_ids.append(key_id)

        for op in ops:
            if op == "rotate":
                # Rotate-on-revoked returns 409 by design; we accept
                # both 200 and 409 here because the simulation
                # already accounts for the no-emission case.
                rot = await async_client.post(
                    f"/api/v1/api-keys/{key_id}/rotate",
                    headers=owner_headers,
                )
                assert rot.status_code in (200, 409), rot.text
            elif op == "revoke":
                rev = await async_client.post(
                    f"/api/v1/api-keys/{key_id}/revoke",
                    headers=owner_headers,
                )
                assert rev.status_code == 200, rev.text
            elif op == "admin_revoke":
                arv = await async_client.post(
                    f"/api/v1/admin/api-keys/{key_id}/revoke",
                    headers=admin_headers,
                )
                assert arv.status_code == 200, arv.text
            else:  # pragma: no cover — strategy is closed under the enum
                raise AssertionError(f"unexpected op kind: {op!r}")

    return key_ids


async def _read_audit_rows(
    db_session, key_ids: List[str]
) -> List[Tuple[str, str, str, str]]:
    """Read back every audit row whose ``resource_id`` is in ``key_ids``.

    Scoping the read by ``resource_id`` keeps the assertion bounded
    to the keys this Hypothesis example created, so audit rows from
    earlier examples in the same test invocation are ignored. The
    rows are ordered by ``id`` to match the natural insertion order
    used by the reference simulator; ordering is not part of the
    property contract (we compare multisets) but is convenient for
    debugging shrunk failures.
    """
    if not key_ids:
        return []
    # Expire the session's identity map first: routes commit through a
    # different sub-transaction, and stale objects can mask freshly
    # written audit rows when the session was first used during setup.
    await db_session.commit()
    result = await db_session.execute(
        select(AuditLog)
        .where(AuditLog.resource_id.in_(key_ids))
        .order_by(AuditLog.id.asc())
    )
    rows = list(result.scalars().all())
    return [
        (r.action, r.user_id, r.resource_type, r.resource_id)
        for r in rows
    ]


def _multiset(rows: List[Tuple[str, str, str, str]]) -> Dict[Tuple[str, str, str, str], int]:
    """Count occurrences of each tuple to compare without ordering."""
    counts: Dict[Tuple[str, str, str, str], int] = {}
    for row in rows:
        counts[row] = counts.get(row, 0) + 1
    return counts


# ── Property ──────────────────────────────────────────────────────────


# Feature: api-platform-export, Property 19: Audit emission for terminal transitions
# Validates: Requirements 7.1, 9.4
@pytest.mark.asyncio
@given(plans=_key_plans())
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p19_api_key_audit_emission_matches_reference(
    plans: List[List[str]],
    no_txn_async_client,
    no_txn_db_session,
) -> None:
    """Live audit emissions equal the simulated multiset for every plan.

    Generates a sequence of API-key lifecycle operations, drives them
    through the live FastAPI routes, simulates the same sequence
    against the reference state machine, and asserts the multiset of
    ``(action, user_id, resource_type, resource_id)`` audit rows
    written to ``audit_logs`` matches the simulation exactly.
    """
    owner = await _make_user(no_txn_db_session, is_admin=False)
    admin = await _make_user(no_txn_db_session, is_admin=True)
    owner_token = create_access_token(owner.id)
    admin_token = create_access_token(admin.id)

    key_ids = await _drive_plan(
        async_client=no_txn_async_client,
        plans=plans,
        owner_token=owner_token,
        admin_token=admin_token,
    )

    expected = _simulate(
        plans=plans,
        owner_id=owner.id,
        admin_id=admin.id,
        key_ids=key_ids,
    )
    actual = await _read_audit_rows(no_txn_db_session, key_ids)

    assert _multiset(actual) == _multiset(expected), (
        "Audit emission disagreed with reference state machine.\n"
        f"plans={plans!r}\n"
        f"key_ids={key_ids!r}\n"
        f"expected={expected!r}\n"
        f"actual={actual!r}"
    )

    # Cross-check the verb-set: every emitted action verb must be one
    # of the four api_key terminal-transition verbs scoped by
    # design.md §Property 19. This guards against a regression where
    # the route layer emits a non-canonical verb under the same
    # ``resource_type='api_key'`` umbrella.
    allowed_verbs: Set[str] = {
        "api_key.create",
        "api_key.rotate",
        "api_key.revoke",
        "api_key.admin_revoke",
    }
    actual_verbs = {row[0] for row in actual}
    assert actual_verbs <= allowed_verbs, (
        f"Unexpected audit verb on api_key resource: "
        f"{actual_verbs - allowed_verbs}"
    )

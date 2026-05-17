"""Property test P23: Compliance export inclusion.

Per design.md §Property 23 (Requirement 9.5) the T10 PIPL/GDPR
compliance export endpoint must include every audit row whose
``action`` belongs to the new T15 verb set
(:data:`app.core.audit.API_PLATFORM_VERBS`) and whose ``created_at``
falls within the requested time range. Without that wiring the
rate-limit, API key, webhook, and export audit rows would be
invisible to compliance review even though they live in the same
``audit_logs`` table.

The endpoint under test is
``GET /api/v1/compliance/audit-export``
(see :mod:`app.api.v1.compliance`), which delegates to
:func:`app.services.audit_query.query_audit_logs`. The contract
guaranteed by Task 17.1 is that no verb whitelist is applied — the
sentinel
:data:`app.services.audit_query._COMPLIANCE_EXPORT_VERB_WHITELIST`
is ``None`` — so the export must surface every verb.

Strategy
--------

For each Hypothesis example we:

1. Provision a fresh JWT-authenticated reviewer (any user passes the
   ``audit:read`` scope check; JWT principals carry the wildcard
   scope per :func:`app.core.deps.require_scope`).
2. Insert one audit row per verb in
   :data:`app.core.audit.API_PLATFORM_VERBS`. Hypothesis only chooses
   the *order* in which the rows are inserted and a small per-row
   detail payload; the verb set itself is fixed because Property 23
   asserts that *every* T15 verb appears in the export, so the
   enumeration is the right boundary.
3. Call ``GET /api/v1/compliance/audit-export`` with a
   wide-enough ``since`` / ``until`` window to capture the rows we
   just inserted.
4. Assert every inserted ``(action, resource_id)`` pair appears in
   the response.

The fixture pattern matches :mod:`test_property_admin_inventory`: we
use the standard ``async_client`` / ``db_session`` because the
compliance export endpoint is read-only and reads through the same
dependency-overridden session that flushed the test rows. No
``session.commit()`` is required — the route's read sees the
flushed rows via the shared transaction.

We cap ``max_examples`` at 25 because every example writes 16 audit
rows (one per verb in :data:`API_PLATFORM_VERBS`), and that is
enough to exercise the property without making the test
prohibitively slow against the live test database.

# Feature: api-platform-export, Property 23: Compliance export inclusion
# Validates: Requirements 9.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from app.core.audit import API_PLATFORM_VERBS
from app.core.security import create_access_token, hash_password
from app.models.audit_log import AuditLog
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────


def _resource_type_for(verb: str) -> str:
    """Map a T15 verb to its canonical ``resource_type`` value.

    Mirrors design §Component 10 / Req 7 AC1-AC5 so the inserted
    rows look exactly like the rows the live route handlers would
    emit. The compliance export does not filter on
    ``resource_type``, so the property holds regardless of this
    mapping; we mirror the production shape so a row that arrives in
    the export looks indistinguishable from a real audit row.
    """
    if verb.startswith("api_key."):
        return "api_key"
    if verb.startswith("webhook.subscription."):
        return "webhook_subscription"
    if verb.startswith("webhook.delivery."):
        return "webhook_delivery"
    if verb.startswith("export.job."):
        return "export_job"
    if verb == "rate_limit.rejected":
        return "api_key"
    if verb == "rate_limiter.backend_unavailable":
        return "system"
    raise AssertionError(f"unmapped verb {verb!r}")  # pragma: no cover


async def _make_reviewer(db_session) -> User:
    """Insert a fresh reviewer user and return it.

    The compliance audit-export endpoint requires the ``audit:read``
    scope, which JWT principals satisfy automatically via the
    wildcard scope. The reviewer therefore does not need
    ``is_admin``; we set it anyway to match the typical compliance
    operator profile and keep the test self-contained if the route
    ever adds an additional ``is_admin`` gate.
    """
    user = User(
        id=str(uuid.uuid4()),
        email=f"p23-reviewer-{uuid.uuid4()}@example.test",
        hashed_password=hash_password("Test1234!"),
        display_name="P23 reviewer",
        is_admin=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _insert_audit_rows(
    db_session,
    user: User,
    verbs_in_order: List[str],
    base_time: datetime,
) -> List[Tuple[str, str]]:
    """Insert one audit row per verb in the supplied order.

    Each row carries:

    * ``action`` — the verb literal.
    * ``resource_type`` — the canonical mapping from
      :func:`_resource_type_for`.
    * ``resource_id`` — a fresh UUID so rows from different
      Hypothesis examples never collide and the response can be
      filtered on the test-owned ids alone.
    * ``user_id`` — the reviewer (acceptable for test data; the
      route does not filter on actor).
    * ``created_at`` — staggered one second per row from
      ``base_time`` so the response's natural newest-first ordering
      is deterministic.
    * ``details`` — a small dict so the JSONB column round-trips
      through the response schema.

    Args:
        db_session: Active async database session.
        user: Reviewer user used to populate ``user_id``.
        verbs_in_order: Hypothesis-permuted list of verbs to insert.
        base_time: Anchor timestamp; each row is offset
            ``i`` seconds after this anchor.

    Returns:
        A list of ``(action, resource_id)`` tuples in insertion
        order. The caller asserts every tuple appears in the export
        response.
    """
    inserted: List[Tuple[str, str]] = []
    for i, verb in enumerate(verbs_in_order):
        resource_id = str(uuid.uuid4())
        row = AuditLog(
            user_id=user.id,
            action=verb,
            resource_type=_resource_type_for(verb),
            resource_id=resource_id,
            details={"p23_marker": True, "verb": verb},
            ip_address=None,
            user_agent=None,
            created_at=base_time + timedelta(seconds=i),
        )
        db_session.add(row)
        await db_session.flush()
        inserted.append((verb, resource_id))
    return inserted


# ── Strategies ────────────────────────────────────────────────────────

# The verb set is fixed; Hypothesis only chooses the order in which
# rows are inserted. ``permutations`` would explore the full
# factorial space (16!) which is far larger than needed; sampling
# from the verb set with replacement turned off via ``shuffle`` over
# the canonical list gives a representative permutation per example
# without blowing up the search space.
_SORTED_VERBS: List[str] = sorted(API_PLATFORM_VERBS)


@st.composite
def _verb_orderings(draw: st.DrawFn) -> List[str]:
    """Generate a permutation of the canonical T15 verb set.

    Uses :func:`hypothesis.strategies.permutations` to draw a single
    ordering of the full 16-verb list per example. Hypothesis can
    shrink this toward the canonical sorted order, which keeps
    counter-examples easy to read.
    """
    return draw(st.permutations(_SORTED_VERBS))


# ── Property ──────────────────────────────────────────────────────────


# Feature: api-platform-export, Property 23: Compliance export inclusion
# Validates: Requirements 9.5
@pytest.mark.asyncio
@given(verbs_in_order=_verb_orderings())
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p23_every_t15_verb_in_window_appears_in_export(
    verbs_in_order: List[str],
    async_client,
    db_session,
) -> None:
    """Every inserted T15 audit row appears in the compliance export.

    The property: for any state of ``audit_logs`` containing rows
    drawn from :data:`API_PLATFORM_VERBS` in any order, when the
    compliance export endpoint is called over a window that covers
    those rows' ``created_at`` timestamps, the response contains
    every inserted row's ``(action, resource_id)`` pair.

    Mechanics:

    1. Insert 16 audit rows (one per verb) staggered one second
       apart, anchored 30 minutes before "now" so the default
       trailing 30-day window in the route would also catch them.
    2. Call the export with an explicit ``since`` / ``until`` that
       brackets the inserted rows.
    3. Read back the response and assert every inserted
       ``(action, resource_id)`` tuple is present.

    The assertion is one-directional (we don't claim the response
    contains *only* our rows) because earlier Hypothesis examples
    in the same test invocation may have left rows in the table —
    this is exactly the scenario the spec intends to support, and
    asserting subset inclusion is the correct expression of
    Property 23.
    """
    reviewer = await _make_reviewer(db_session)

    # Anchor inserts 30 minutes ago so every row's timestamp falls
    # comfortably inside both the explicit ``since``/``until`` and
    # the route's 30-day default window.
    now = datetime.now(timezone.utc)
    base_time = now - timedelta(minutes=30)
    inserted = await _insert_audit_rows(
        db_session, reviewer, verbs_in_order, base_time
    )

    # Sanity guard: every T15 verb must be exercised exactly once
    # so the property statement itself is well-formed.
    assert len(inserted) == len(API_PLATFORM_VERBS)
    assert {v for v, _ in inserted} == set(API_PLATFORM_VERBS)

    # Confirm the rows actually committed via the same session the
    # route will read from. The default ``db_session`` fixture
    # wraps the test in ``session.begin()``, and the FastAPI
    # dependency override gives the route the same session — so a
    # flush is sufficient and a commit would close the surrounding
    # transaction.
    table_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.resource_id.in_([rid for _, rid in inserted])
            )
        )
    ).scalars().all()
    assert len(table_rows) == len(inserted), (
        "audit_logs flush did not persist every inserted row; "
        f"inserted={len(inserted)} table={len(table_rows)}"
    )

    reviewer_token = create_access_token(reviewer.id)
    headers = {"Authorization": f"Bearer {reviewer_token}"}

    # Bracket the inserted rows with a generous window. The export
    # endpoint applies an exclusive upper bound on ``created_at``,
    # so we extend ``until`` past the last row by a full minute.
    since = base_time - timedelta(seconds=1)
    until = now + timedelta(minutes=1)
    # Lift the page size to the route's documented ceiling so a
    # single call is enough even if other Hypothesis examples in
    # the same test invocation have already populated rows.
    resp = await async_client.get(
        "/api/v1/compliance/audit-export",
        params={
            "since": since.isoformat(),
            "until": until.isoformat(),
            "limit": 5000,
        },
        headers=headers,
    )
    assert resp.status_code == 200, (
        f"compliance audit-export should return 200; got "
        f"{resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert isinstance(body, list), (
        f"compliance audit-export must return a JSON array; got "
        f"{type(body).__name__}"
    )

    # Build a set of (action, resource_id) pairs from the response
    # and assert every inserted pair is included.
    response_pairs = {
        (row["action"], row["resource_id"]) for row in body
    }
    inserted_pairs = set(inserted)
    missing = inserted_pairs - response_pairs
    assert not missing, (
        "Compliance export omitted T15 audit rows that fall in the "
        "requested window — Req 9.5 violated.\n"
        f"missing pairs: {sorted(missing)!r}\n"
        f"inserted: {sorted(inserted_pairs)!r}\n"
        f"response pair count: {len(response_pairs)}"
    )

    # Cross-check the verb set: every T15 verb must appear at
    # least once in the response. This is implied by the pair
    # subset check above but pinning it here gives a clearer error
    # if the response shape ever drops the ``action`` field.
    response_verbs = {row["action"] for row in body}
    missing_verbs = API_PLATFORM_VERBS - response_verbs
    assert not missing_verbs, (
        "Compliance export response missing T15 verbs from the "
        f"window: {sorted(missing_verbs)!r}"
    )


# ── Empty-window pin ──────────────────────────────────────────────────


# Feature: api-platform-export, Property 23: Compliance export inclusion
# Validates: Requirements 9.5
@pytest.mark.asyncio
async def test_p23_verbs_outside_window_are_not_required_to_appear(
    async_client,
    db_session,
) -> None:
    """Sanity pin: rows outside the requested window are not asserted.

    Property 23 only requires inclusion of in-window rows — rows
    *outside* ``[since, until]`` are not part of the property
    statement. This test inserts a single verb 90 days in the past
    and queries a 1-day window; the row is permitted to be absent
    from the response. Pinning this clause guards against a future
    over-tightening of the property.
    """
    reviewer = await _make_reviewer(db_session)
    now = datetime.now(timezone.utc)
    far_past = now - timedelta(days=90)

    out_of_window = AuditLog(
        user_id=reviewer.id,
        action="api_key.create",
        resource_type="api_key",
        resource_id=str(uuid.uuid4()),
        details={"p23_marker": True, "out_of_window": True},
        created_at=far_past,
    )
    db_session.add(out_of_window)
    await db_session.flush()

    reviewer_token = create_access_token(reviewer.id)
    headers = {"Authorization": f"Bearer {reviewer_token}"}
    since = now - timedelta(days=1)
    until = now + timedelta(minutes=1)
    resp = await async_client.get(
        "/api/v1/compliance/audit-export",
        params={
            "since": since.isoformat(),
            "until": until.isoformat(),
            "limit": 5000,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    response_resource_ids = {row.get("resource_id") for row in body}
    assert out_of_window.resource_id not in response_resource_ids, (
        "Compliance export returned a row whose created_at is "
        "outside the requested window; the route must respect "
        "since/until bounds."
    )

"""Property test P20: Audit log query equivalence.

Per design.md §Property 20 (Requirements 7.7), the admin audit-logs
endpoint ``GET /api/v1/admin/audit-logs`` must return exactly the
``audit_logs`` rows that satisfy the same filter the route documents
— modulo pagination ordering. The endpoint is a thin wrapper over
:func:`app.services.audit_query.query_audit_logs`, which combines all
optional filters with AND semantics and orders results by
``created_at DESC``. The property holds in two directions: every
table row matching the in-memory predicate must appear in the
response, and every response row must be a real table row that
satisfies the same predicate.

Strategy
--------

We populate the ``audit_logs`` table with a small random set of rows
spanning two acting users, two resource types, several action verbs,
and a deterministic three-day creation window. Hypothesis then draws
filter combinations from the cross product of those axes — including
the empty-filter case and combinations that select zero rows — and
we assert that the response row-id set equals the set the in-memory
reference filter computes from the same table snapshot.

The reference filter mirrors :func:`query_audit_logs` exactly:

* ``actor_user_id`` matches ``AuditLog.user_id`` for equality.
* ``resource_type`` matches ``AuditLog.resource_type`` for equality.
* ``resource_id`` matches ``AuditLog.resource_id`` for equality.
* ``action`` matches ``AuditLog.action`` for equality.
* ``since`` is an inclusive lower bound on ``created_at``.
* ``until`` is an exclusive upper bound on ``created_at``.

Because the audit table is append-only and the rows are inserted in
deterministic ``created_at`` order with a strictly increasing offset
per row, the descending-time ordering the route emits is bijective
with descending row-id ordering, so a set-equality assertion on ids
is sufficient to validate the filter clauses. We separately assert
the response is sorted ``created_at DESC`` so the ordering clause is
covered without a stable secondary key dependency.

We cap ``max_examples`` at 20 per the project convention for
DB-bound property tests (see :mod:`tests.test_property_admin_inventory`)
because every example writes several rows and the property reduces
to a small enumerated state machine. The
:class:`HealthCheck.function_scoped_fixture` suppression mirrors that
file's rationale: the conftest ``db_session`` / ``async_client``
fixtures are intentionally function-scoped to give Hypothesis one
shared transaction across the examples within a single test
invocation.

# Feature: api-platform-export, Property 20: Audit log query equivalence
# Validates: Requirements 7.7
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.audit_log import AuditLog
from app.models.user import User


# ── Test fixture data ─────────────────────────────────────────────────


#: Deterministic ``created_at`` anchor for every test row. We seed
#: rows at one-hour offsets from this anchor so the ``since`` /
#: ``until`` filter strategy can pick boundary timestamps that fall
#: inside, on, and outside the populated range.
_T0 = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

#: Number of rows seeded per Hypothesis example. Eight rows across
#: two actors, two resource types, and a four-verb vocabulary covers
#: every filter axis cross-product without slowing the inner loop.
_ROW_COUNT = 8

#: The small action verbs the seeder draws from. Chosen to span both
#: api-key and webhook resource types so cross-resource filters can
#: exercise non-trivial AND semantics.
_VERBS = (
    "api_key.create",
    "api_key.revoke",
    "webhook.subscription.create",
    "webhook.subscription.delete",
)

#: Resource types parallel to ``_VERBS``. The mapping is fixed: the
#: api-key verbs use ``api_key`` and the webhook verbs use
#: ``webhook_subscription``.
_RESOURCE_TYPE_FOR_VERB = {
    "api_key.create": "api_key",
    "api_key.revoke": "api_key",
    "webhook.subscription.create": "webhook_subscription",
    "webhook.subscription.delete": "webhook_subscription",
}


# ── Strategies ────────────────────────────────────────────────────────


# Each filter axis is sampled independently with ``st.none()`` mixed
# in so the empty-filter case (every axis set to ``None``) is reached
# by Hypothesis with non-trivial probability. The values are drawn
# from the seeded row population plus deliberately-absent values so
# the property covers both the "match" and "miss" branches per axis.

_actor_filter_strategy = st.one_of(
    st.none(),
    st.sampled_from(["__ACTOR_A__", "__ACTOR_B__", "__ACTOR_NONEXISTENT__"]),
)

_resource_type_filter_strategy = st.one_of(
    st.none(),
    st.sampled_from(
        ["api_key", "webhook_subscription", "__RT_NONEXISTENT__"]
    ),
)

_resource_id_filter_strategy = st.one_of(
    st.none(),
    # Index into the seeded resource_id list at run time. We sample an
    # index here and resolve it inside the test against the seeded
    # rows so the strategy stays side-effect-free.
    st.integers(min_value=0, max_value=_ROW_COUNT - 1),
    st.just("__RID_NONEXISTENT__"),
)

_action_filter_strategy = st.one_of(
    st.none(),
    st.sampled_from(list(_VERBS) + ["__ACTION_NONEXISTENT__"]),
)

# ``since`` and ``until`` are sampled as integer hour offsets relative
# to ``_T0`` and converted to datetimes inside the test. Offsets span
# from before the first seeded row to after the last, including the
# boundary moments themselves so the inclusive-lower / exclusive-upper
# semantics are covered.
_time_offset_strategy = st.one_of(
    st.none(),
    st.integers(min_value=-1, max_value=_ROW_COUNT + 1),
)


# ── Helpers ──────────────────────────────────────────────────────────


def _hour(offset: int) -> datetime:
    """Return ``_T0 + offset hours`` as a UTC datetime."""
    return _T0 + timedelta(hours=offset)


async def _make_admin_user(db_session) -> User:
    """Provision an admin user and return it.

    The audit-logs route is gated on the ``audit:read`` scope plus
    ``is_admin``; we only need a JWT-authenticated admin caller for
    the route, so a single user with ``is_admin=True`` is enough.
    """
    admin = User(
        id=str(uuid.uuid4()),
        email=f"p20-admin-{uuid.uuid4()}@example.test",
        hashed_password=hash_password("Test1234!"),
        display_name="P20 admin",
        is_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()
    return admin


async def _seed_audit_rows(
    db_session, actor_a_id: str, actor_b_id: str
) -> List[AuditLog]:
    """Insert ``_ROW_COUNT`` deterministic audit rows.

    The rows alternate actors, span the full ``_VERBS`` vocabulary,
    and step ``created_at`` by one hour per row so the time-range
    filter has well-defined boundaries. Each row carries a unique
    UUID ``resource_id`` so the resource-id filter can target
    individual rows. The seeded rows are returned to the caller in
    insertion order so the test can resolve resource-id indices into
    concrete strings.

    Args:
        db_session: Active async database session.
        actor_a_id: UUID of the first acting user.
        actor_b_id: UUID of the second acting user.

    Returns:
        List of :class:`AuditLog` rows in insertion order.
    """
    rows: List[AuditLog] = []
    for idx in range(_ROW_COUNT):
        verb = _VERBS[idx % len(_VERBS)]
        resource_type = _RESOURCE_TYPE_FOR_VERB[verb]
        actor_id = actor_a_id if idx % 2 == 0 else actor_b_id
        row = AuditLog(
            user_id=actor_id,
            action=verb,
            resource_type=resource_type,
            resource_id=str(uuid.uuid4()),
            details={"seed_index": idx},
            ip_address=None,
            user_agent=None,
            created_at=_hour(idx),
        )
        db_session.add(row)
        rows.append(row)
    await db_session.flush()
    return rows


def _reference_filter(
    rows: List[AuditLog],
    *,
    actor_user_id: Optional[str],
    resource_type: Optional[str],
    resource_id: Optional[str],
    action: Optional[str],
    since: Optional[datetime],
    until: Optional[datetime],
) -> List[AuditLog]:
    """Compute the expected filtered row set in memory.

    Mirrors :func:`app.services.audit_query.query_audit_logs` clause
    by clause. AND semantics across axes; the order returned is
    descending by ``created_at`` to match the route contract.
    """
    out: List[AuditLog] = []
    for r in rows:
        if actor_user_id is not None and r.user_id != actor_user_id:
            continue
        if resource_type is not None and r.resource_type != resource_type:
            continue
        if resource_id is not None and r.resource_id != resource_id:
            continue
        if action is not None and r.action != action:
            continue
        if since is not None and r.created_at < since:
            continue
        if until is not None and r.created_at >= until:
            continue
        out.append(r)
    out.sort(key=lambda r: r.created_at, reverse=True)
    return out


def _resolve_resource_id_filter(
    raw: object, seeded: List[AuditLog]
) -> Optional[str]:
    """Resolve the resource-id filter strategy into a concrete value.

    The strategy emits ``None`` (no filter), an integer index into
    the seeded rows, or the literal nonexistent placeholder. This
    helper turns each variant into the value the route expects.
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        return seeded[raw].resource_id
    if isinstance(raw, str):
        return raw
    raise TypeError(
        f"unexpected resource_id strategy value: {raw!r}"
    )


def _resolve_actor_filter(
    raw: Optional[str],
    actor_a_id: str,
    actor_b_id: str,
) -> Optional[str]:
    """Map the actor-strategy placeholder to a real user id."""
    if raw is None:
        return None
    if raw == "__ACTOR_A__":
        return actor_a_id
    if raw == "__ACTOR_B__":
        return actor_b_id
    if raw == "__ACTOR_NONEXISTENT__":
        # A syntactically valid UUID that no row carries.
        return "00000000-0000-0000-0000-000000000000"
    raise ValueError(f"unexpected actor strategy value: {raw!r}")


# ── Property ─────────────────────────────────────────────────────────


# Feature: api-platform-export, Property 20: Audit log query equivalence
# Validates: Requirements 7.7
@pytest.mark.asyncio
@given(
    actor_choice=_actor_filter_strategy,
    resource_type_choice=_resource_type_filter_strategy,
    resource_id_choice=_resource_id_filter_strategy,
    action_choice=_action_filter_strategy,
    since_offset=_time_offset_strategy,
    until_offset=_time_offset_strategy,
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p20_admin_audit_logs_filter_equivalence(
    actor_choice,
    resource_type_choice,
    resource_id_choice,
    action_choice,
    since_offset,
    until_offset,
    async_client,
    db_session,
) -> None:
    """``/admin/audit-logs`` filter equals the in-memory reference filter.

    For each Hypothesis example, seed a fresh population of audit
    rows, draw a filter combination, call the admin route with the
    same filter, and assert set equality between the response row
    ids and the in-memory reference's row ids. The descending-time
    ordering clause is asserted independently because two rows can
    share a ``created_at`` only at one-hour resolution and the seeder
    keeps offsets unique.
    """
    admin = await _make_admin_user(db_session)
    actor_a = await _make_admin_user(db_session)  # second non-admin actor reuse
    actor_b = await _make_admin_user(db_session)
    # The two actor rows above happen to be admins, but the audit
    # filter never reads ``is_admin``; the only requirement is they
    # are valid user UUIDs the audit_logs.user_id FK accepts.
    seeded = await _seed_audit_rows(db_session, actor_a.id, actor_b.id)

    actor_user_id = _resolve_actor_filter(
        actor_choice, actor_a.id, actor_b.id
    )
    resource_id = _resolve_resource_id_filter(resource_id_choice, seeded)
    resource_type = (
        None if resource_type_choice is None else resource_type_choice
    )
    action = action_choice
    since = None if since_offset is None else _hour(since_offset)
    until = None if until_offset is None else _hour(until_offset)

    expected = _reference_filter(
        seeded,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        since=since,
        until=until,
    )
    expected_ids = [r.id for r in expected]

    params = {}
    if actor_user_id is not None:
        params["actor_user_id"] = actor_user_id
    if resource_type is not None:
        params["resource_type"] = resource_type
    if resource_id is not None:
        params["resource_id"] = resource_id
    if action is not None:
        params["action"] = action
    if since is not None:
        params["since"] = since.isoformat()
    if until is not None:
        params["until"] = until.isoformat()
    # Page the response generously so we never truncate the expected
    # set; the audit-logs endpoint caps ``limit`` server-side and the
    # default is well above the seeded count.
    params["limit"] = 200

    admin_token = create_access_token(admin.id)
    resp = await async_client.get(
        "/api/v1/admin/audit-logs",
        params=params,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list), (
        "audit-logs route must return a JSON array; got "
        f"{type(body).__name__}"
    )

    response_ids = [row["id"] for row in body]

    # Filter clause: set equality on row ids between response and
    # reference. Comparing as sets isolates the filter property from
    # the ordering property below.
    assert set(response_ids) == set(expected_ids), (
        "Admin audit-logs filter disagreed with reference filter.\n"
        f"params={params!r}\n"
        f"response_ids={sorted(response_ids)!r}\n"
        f"expected_ids={sorted(expected_ids)!r}\n"
        "missing_from_response="
        f"{sorted(set(expected_ids) - set(response_ids))!r}\n"
        "extra_in_response="
        f"{sorted(set(response_ids) - set(expected_ids))!r}"
    )

    # Ordering clause: response must be sorted by ``created_at`` in
    # descending order. The seeder keeps every ``created_at``
    # distinct, so ties cannot mask an ordering violation.
    response_times = [row["created_at"] for row in body]
    assert response_times == sorted(response_times, reverse=True), (
        "Admin audit-logs response is not ordered by created_at "
        "DESC.\n"
        f"params={params!r}\n"
        f"response_times={response_times!r}"
    )


# Feature: api-platform-export, Property 20: Audit log query equivalence
# Validates: Requirements 7.7
@pytest.mark.asyncio
async def test_p20_audit_log_query_helper_filter_equivalence(
    db_session,
) -> None:
    """The :func:`query_audit_logs` helper itself agrees with the reference.

    Goes one layer below the HTTP route to assert that the SQL the
    helper emits applies the same AND-of-equalities + half-open time
    range the in-memory reference uses. This pin protects against a
    refactor that changes the helper's clause set without updating
    the route, which the route-level test alone could mask if the
    route happened to layer in additional filtering of its own.
    """
    from app.services.audit_query import query_audit_logs

    actor_a = await _make_admin_user(db_session)
    actor_b = await _make_admin_user(db_session)
    seeded = await _seed_audit_rows(db_session, actor_a.id, actor_b.id)

    # Spot-check three representative filter combinations directly
    # against the helper: actor only, time-range only, and a
    # cross-axis combination that hits the AND semantics.
    cases: List[Tuple[dict, List[AuditLog]]] = []

    case_actor = {"actor_user_id": actor_a.id}
    cases.append(
        (
            case_actor,
            _reference_filter(
                seeded,
                actor_user_id=actor_a.id,
                resource_type=None,
                resource_id=None,
                action=None,
                since=None,
                until=None,
            ),
        )
    )

    case_time = {"since": _hour(2), "until": _hour(5)}
    cases.append(
        (
            case_time,
            _reference_filter(
                seeded,
                actor_user_id=None,
                resource_type=None,
                resource_id=None,
                action=None,
                since=_hour(2),
                until=_hour(5),
            ),
        )
    )

    case_combo = {
        "actor_user_id": actor_b.id,
        "resource_type": "api_key",
        "action": "api_key.revoke",
    }
    cases.append(
        (
            case_combo,
            _reference_filter(
                seeded,
                actor_user_id=actor_b.id,
                resource_type="api_key",
                resource_id=None,
                action="api_key.revoke",
                since=None,
                until=None,
            ),
        )
    )

    for kwargs, expected in cases:
        rows = await query_audit_logs(db_session, **kwargs, limit=200)
        response_ids = {r.id for r in rows}
        expected_ids = {r.id for r in expected}
        assert response_ids == expected_ids, (
            "query_audit_logs helper disagreed with reference filter.\n"
            f"kwargs={kwargs!r}\n"
            f"response_ids={sorted(response_ids)!r}\n"
            f"expected_ids={sorted(expected_ids)!r}"
        )

        # Helper must also order DESC by created_at.
        response_times = [r.created_at for r in rows]
        assert response_times == sorted(
            response_times, reverse=True
        ), (
            "query_audit_logs helper did not return rows in "
            "created_at DESC order.\n"
            f"kwargs={kwargs!r}\n"
            f"response_times={response_times!r}"
        )

    # Verify the conflict-guard clause: passing both ``action`` and
    # ``actions`` is rejected, per the helper's own contract.
    with pytest.raises(ValueError):
        await query_audit_logs(
            db_session,
            action="api_key.create",
            actions=["api_key.create"],
        )

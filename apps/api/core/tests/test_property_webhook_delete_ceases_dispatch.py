"""Property test P4 (webhook clause): delete ceases subsequent dispatch.

Per design §Property 4 (Requirement 3.6), soft-deleting a webhook
subscription must stop the platform from creating any new
``WebhookDelivery`` rows for that subscription on subsequent matching
domain events. The subscription itself remains in
``webhook_subscriptions`` with ``active`` set to ``False`` (per the
soft-delete contract documented on
:class:`app.models.webhook_subscription.WebhookSubscription`); the
fan-out path in :func:`app.services.webhook_emitter.emit_webhook_event`
filters those rows out before inserting deliveries.

This module exercises the webhook clause of Property 4. The companion
sub-task 4.5 covers the API-key clause (revoked keys cease activity)
in a separate test file.

Strategy
--------

For every Hypothesis example we:

1. Insert a fresh JWT-authenticated owner via a per-example committing
   session, create a survey owned by that user, and grant the user a
   ``viewer`` row on the survey so the emitter's permission gate
   passes when we later emit an event scoped to that survey. A unique
   email per example keeps owners from colliding across the
   function-scoped fixture lifetime.
2. Create ``n`` (drawn from 1..4) webhook subscriptions through
   ``POST /api/v1/webhooks/``, each subscribed to the same event type
   (``response.created``) and account-scoped (``survey_id`` left
   ``None``) so the only thing that varies between subscriptions is
   their identity. The route persists each subscription with
   ``active=True``.
3. Pick a deleted subset using a 4-bit bitmask drawn from
   ``[0, 2 ** 4 - 1]``. Bit ``i`` set means subscription ``i`` is
   soft-deleted via ``DELETE /api/v1/webhooks/{sub_id}``. The bitmask
   covers the empty subset (no deletes), the full subset (all
   deletes), and every middle subset, so Hypothesis exercises the
   property at the boundaries the partition method would otherwise
   miss.
4. Emit one ``response.created`` event scoped to the survey via
   :func:`app.services.webhook_emitter.emit_webhook_event` and commit.
5. Query ``webhook_deliveries`` for the new event and assert the row
   count per subscription matches the expected pattern: every deleted
   subscription has zero new deliveries; every surviving subscription
   has exactly one new delivery whose ``event_type`` equals the
   emitted event type. A new delivery created against a deleted
   subscription would refute the property.

Session-management note
-----------------------

The shared ``conftest.db_session`` fixture wraps the test in
``async with session.begin() as transaction:`` and rolls back at
teardown. That pattern is incompatible with property tests that hit
committing routes across many Hypothesis examples: the first route
``db.commit()`` closes the wrapper's inner transaction, and the second
example then trips
``InvalidRequestError: Can't operate on closed transaction inside
context manager`` on the next session operation. To avoid that
brittleness we build a per-test session factory bound to the
function-scoped ``test_engine`` and override
:func:`app.database.get_db` ourselves, giving each route call a fresh,
autocommit-style session and using a separate fresh session for
in-test verification queries and the direct emitter call. This mirrors
the ``p19_*`` fixture pattern in
``test_property_webhook_subscription_audit_emission.py``.

# Feature: api-platform-export, Property 4: Revoke and delete cease subsequent activity (webhook clause)
# Validates: Requirements 3.6
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator, List, Tuple

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings, strategies as st
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import create_access_token, hash_password
from app.database import get_db
from app.main import app
from app.models.survey import Survey
from app.models.survey_permission import SurveyPermission
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery
from app.services.webhook_emitter import emit_webhook_event


# ── Constants ─────────────────────────────────────────────────────────

#: Event type used for both subscription registration and the post-delete
#: emission. Pinning a single event type keeps the strategy small and
#: makes the row-count assertion crisp: every surviving subscription
#: receives exactly one new delivery, never two.
_EVENT_TYPE: str = "response.created"

#: Upper bound on the number of subscriptions per example. Four keeps
#: each Hypothesis example fast (each subscription costs one ``POST``
#: round-trip) while still exercising the empty / all / middle subset
#: shapes documented in the test brief. The bitmask strategy below is
#: sized to match.
_MAX_SUBSCRIPTIONS: int = 4


# ── Strategies ────────────────────────────────────────────────────────

#: Number of subscriptions to create per example. ``min_value=1``
#: because deleting nothing on an empty subscription set carries no
#: information about the property.
_N_SUBSCRIPTIONS = st.integers(min_value=1, max_value=_MAX_SUBSCRIPTIONS)

#: 4-bit deletion bitmask. Bit ``i`` (LSB-indexed) set means
#: subscription ``i`` is deleted; cleared means it survives. The full
#: range ``[0, 2**4 - 1]`` covers the empty subset (0), the full
#: subset (15), and every middle pattern. When ``n < 4`` the upper
#: bits of the bitmask are ignored by :func:`_decode_deleted_indices`.
_DELETE_BITMASK = st.integers(min_value=0, max_value=(2**_MAX_SUBSCRIPTIONS) - 1)


def _decode_deleted_indices(n: int, bitmask: int) -> List[int]:
    """Return the indices ``i`` in ``[0, n)`` whose bit is set in ``bitmask``.

    Bits at positions ``>= n`` are ignored so the same bitmask
    strategy can drive any ``n`` up to :data:`_MAX_SUBSCRIPTIONS`
    without skewing the distribution: every concrete ``(n, bitmask)``
    example produces a well-defined subset.

    Args:
        n: Number of subscriptions in the example.
        bitmask: Generated 4-bit deletion bitmask.

    Returns:
        Sorted list of subscription indices to delete.
    """
    return [i for i in range(n) if (bitmask >> i) & 1]


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def p4_session_factory(test_engine) -> async_sessionmaker:
    """Build a session factory bound to the function-scoped test engine.

    Each call to the factory yields a fresh :class:`AsyncSession` with
    no outer ``session.begin()`` wrapper, so the route layer's
    ``await db.commit()`` calls succeed without invalidating later
    operations across Hypothesis examples (see module docstring).

    ``expire_on_commit=False`` mirrors the production session factory
    so attribute access on user / subscription rows after commit
    behaves the same way the route does.
    """
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest_asyncio.fixture
async def p4_client(
    p4_session_factory: async_sessionmaker,
) -> AsyncIterator[AsyncClient]:
    """HTTP client that injects a fresh route session per request.

    Replaces the conftest-wide ``async_client`` fixture for this
    property test only. The dependency override returns a brand-new
    session for each ``Depends(get_db)`` resolution, so the route's
    ``await db.commit()`` is the natural commit-and-close pattern
    rather than fighting the conftest's transaction wrapper.
    """

    async def _fresh_route_db() -> AsyncIterator[AsyncSession]:
        async with p4_session_factory() as s:
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


async def _make_owner_with_survey(
    p4_session_factory: async_sessionmaker,
) -> Tuple[str, str, str]:
    """Insert a fresh owner, survey, and viewer permission row.

    The owner is the JWT principal that registers the subscriptions.
    The survey is the event scope used by the post-delete emission;
    the viewer permission row is what the fan-out permission gate in
    :func:`app.services.webhook_emitter.emit_webhook_event` looks for
    when it filters candidate subscriptions. Without that row the
    emitter would correctly drop every candidate even before the
    delete clause has a chance to act, so the property would hold
    vacuously.

    A unique email per call keeps owners from colliding across
    Hypothesis examples that share the function-scoped session
    factory.

    Args:
        p4_session_factory: Factory that yields fresh, autocommitting
            sessions for direct DB writes outside the route layer.

    Returns:
        A tuple ``(user_id, survey_id, jwt_bearer_token)``.
    """
    async with p4_session_factory() as s:
        user = User(
            email=f"p4-webhook-{uuid.uuid4().hex[:12]}@example.com",
            hashed_password=hash_password("Test1234!"),
            display_name="P4 Owner",
        )
        s.add(user)
        await s.flush()

        survey = Survey(
            owner_id=user.id,
            title="P4 webhook delete ceases dispatch",
            json_content={"pages": []},
        )
        s.add(survey)
        await s.flush()

        # Viewer permission is the minimum the emitter's permission
        # gate accepts, mirroring the production fan-out contract.
        s.add(
            SurveyPermission(
                user_id=user.id,
                survey_id=survey.id,
                role="viewer",
            )
        )

        await s.commit()
        await s.refresh(user)
        await s.refresh(survey)
        user_id = user.id
        survey_id = survey.id

    return user_id, survey_id, create_access_token(user_id)


async def _create_subscription(client: AsyncClient, headers: dict) -> str:
    """Create one account-scoped webhook subscription and return its id.

    Account-scoped (``survey_id`` left ``None``) is the simplest shape
    that exercises the property: the emitter's survey-scope filter
    accepts the subscription on every survey the owner can see, so
    the only varying input is the subscription's ``active`` flag,
    which is exactly what the delete route flips.

    The route auto-generates a fresh signing secret and target URL
    validity is enforced; we pass a stable HTTPS target URL because
    the property is independent of URL contents.
    """
    resp = await client.post(
        "/api/v1/webhooks/",
        headers=headers,
        json={
            "target_url": "https://hooks.example.com/p4",
            "event_types": [_EVENT_TYPE],
            "description": "P4 delete ceases dispatch test",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _delete_subscription(
    client: AsyncClient, headers: dict, sub_id: str
) -> None:
    """Hit the DELETE route and assert the soft-delete returns 204.

    The route's idempotency clause means a second delete on an
    already-inactive subscription is a 204 no-op, so this helper is
    safe to call once per planned deletion without further
    coordination.
    """
    resp = await client.delete(
        f"/api/v1/webhooks/{sub_id}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text


async def _emit_one_event(
    p4_session_factory: async_sessionmaker, survey_id: str
) -> None:
    """Run :func:`emit_webhook_event` once and commit.

    Uses a fresh session outside the route layer because the
    subscription set is already persisted by prior route commits;
    the emitter only needs to see it. Committing after the emit
    fixes the new delivery rows in place so the verification query
    can find them with a separate session.
    """
    async with p4_session_factory() as s:
        await emit_webhook_event(
            s,
            event_type=_EVENT_TYPE,
            survey_id=survey_id,
            payload={
                "survey_id": survey_id,
                "response_id": str(uuid.uuid4()),
            },
        )
        await s.commit()


async def _count_deliveries_per_subscription(
    p4_session_factory: async_sessionmaker, sub_ids: List[str]
) -> dict:
    """Return ``{sub_id: count}`` of post-emit deliveries.

    Filters by ``subscription_id IN sub_ids`` so accumulated rows
    from prior Hypothesis examples on the shared engine do not leak
    into the assertion. Each example's subscription ids are unique,
    so the filter is a clean boundary.
    """
    async with p4_session_factory() as s:
        result = await s.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.subscription_id.in_(sub_ids),
                WebhookDelivery.event_type == _EVENT_TYPE,
            )
        )
        rows = list(result.scalars().all())

    counts = {sub_id: 0 for sub_id in sub_ids}
    for row in rows:
        counts[row.subscription_id] = counts.get(row.subscription_id, 0) + 1
    return counts


# ── The property test ────────────────────────────────────────────────


# Feature: api-platform-export, Property 4: Revoke and delete cease subsequent activity (webhook clause)
# Validates: Requirements 3.6
@pytest.mark.asyncio
@given(
    n_subs=_N_SUBSCRIPTIONS,
    delete_bitmask=_DELETE_BITMASK,
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p4_webhook_delete_ceases_dispatch(
    p4_client: AsyncClient,
    p4_session_factory: async_sessionmaker,
    n_subs: int,
    delete_bitmask: int,
) -> None:
    """Soft-deleted subscriptions create zero new deliveries on emission.

    Sub-invariants asserted in lock-step:

    * Every subscription whose index is in the deleted set has zero
      ``WebhookDelivery`` rows for the post-delete emission. A non-zero
      count would refute the property: a soft-deleted subscription
      must not enter the fan-out match set.
    * Every surviving subscription has exactly one new
      ``WebhookDelivery`` row whose ``event_type`` equals the emitted
      event type. A count of zero would mean the emitter dropped a
      legitimate match; a count above one would mean it duplicated.

    The two halves are checked together so a regression that swaps
    the active/deleted predicate (e.g. inverts the ``active`` filter)
    fails on at least one half on every non-empty subset.

    Validates: Requirements 3.6.
    """
    user_id, survey_id, token = await _make_owner_with_survey(
        p4_session_factory
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Create the subscription set in index order so ``sub_ids[i]``
    # is the subscription that the bitmask's bit ``i`` controls.
    sub_ids: List[str] = []
    for _ in range(n_subs):
        sub_ids.append(await _create_subscription(p4_client, headers))

    deleted_indices = _decode_deleted_indices(n_subs, delete_bitmask)
    surviving_indices = [i for i in range(n_subs) if i not in set(deleted_indices)]

    for i in deleted_indices:
        await _delete_subscription(p4_client, headers, sub_ids[i])

    # Emit one matching event after the deletes have committed.
    await _emit_one_event(p4_session_factory, survey_id)

    counts = await _count_deliveries_per_subscription(
        p4_session_factory, sub_ids
    )

    for i in deleted_indices:
        sub_id = sub_ids[i]
        assert counts[sub_id] == 0, (
            f"deleted subscription {sub_id!r} (index {i}) received "
            f"{counts[sub_id]} new deliveries; expected 0. "
            f"deleted_indices={deleted_indices}, n_subs={n_subs}, "
            f"bitmask={delete_bitmask}"
        )

    for i in surviving_indices:
        sub_id = sub_ids[i]
        assert counts[sub_id] == 1, (
            f"surviving subscription {sub_id!r} (index {i}) received "
            f"{counts[sub_id]} new deliveries; expected exactly 1. "
            f"deleted_indices={deleted_indices}, n_subs={n_subs}, "
            f"bitmask={delete_bitmask}"
        )

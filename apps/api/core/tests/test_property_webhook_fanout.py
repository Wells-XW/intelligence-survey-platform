"""Property test P8: Webhook routing fan-out.

Per design §Property 8 (Requirement 4.1), emitting a domain event
through :func:`app.services.webhook_emitter.emit_webhook_event` must
create exactly one ``WebhookDelivery`` row per ``WebhookSubscription``
that satisfies the routing predicate:

    active
    AND (event_type in event_types)
    AND (survey_id IS NULL OR survey_id == event.survey_id)
    AND owner has at least viewer permission on event.survey_id

The owner-permission gate is held constant in this property test. The
test creates one owner who has a ``viewer`` role on the only emitting
survey, so the permission gate is always satisfied for that owner's
subscriptions and the property reduces to the first three conjuncts.
Every subscription this test inserts therefore exercises the same
permission path; the count of deliveries equals the count of
``(active, event_types contains e, survey_id matches)`` matches.

Strategy
--------

For every Hypothesis example we:

1. Insert a fresh owner ``User`` whose email carries a per-example
   uuid suffix so cross-example state cannot collide. The owner
   commits before subscription rows so its FK target exists.
2. Insert a fresh ``Survey`` owned by the owner, plus a
   ``SurveyPermission`` row granting the owner ``viewer`` on that
   survey. The permission gate in
   :func:`app.services.webhook_emitter.emit_webhook_event` only
   checks the existence of a ``SurveyPermission`` row for
   ``(survey_id, user_id)``, so any role qualifies.
3. Insert ``1..5`` ``WebhookSubscription`` rows with a Hypothesis-
   generated ``(active, event_types, survey_id)`` triple drawn from
   ``{True, False} × subsets of {response.created, response.completed,
   quota.reached, distribution.sent} × {survey_a, None}``. Empty
   ``event_types`` sets and ``active=False`` are part of the input
   space — they are the boundary cases that pin the routing
   predicate's first two conjuncts.
4. Call ``emit_webhook_event`` for one Hypothesis-chosen
   ``event_type`` against the owner's survey. The emitter flushes
   one ``WebhookDelivery`` per matching subscription inside the
   caller's transaction.
5. Predict the matching count in-memory using the routing
   predicate restricted to this example's owner; assert the count
   of new ``WebhookDelivery`` rows (post-emit total minus pre-emit
   total) equals the prediction, and that the list of delivery ids
   the emitter returned has the same length.

Cross-example isolation
-----------------------

The function-scoped ``test_engine`` fixture creates the schema once
at test start, so accumulated subscriptions and deliveries from
previous Hypothesis examples are still in the database when the next
example runs. Two mechanisms keep that accumulation from corrupting
the row-count comparison:

* ``WHERE active = TRUE AND event_types @> [event_type]`` plus the
  per-example ``survey_id`` filter exclude any prior-example
  subscription scoped to a different survey.
* The permission gate only matches subscriptions whose owner has a
  ``SurveyPermission`` row on this example's survey. A subscription
  whose ``survey_id IS NULL`` from a prior example will fall
  through to the permission check, but its owner has no permission
  on the new survey, so it is filtered out.

The pre-emit / post-emit ``COUNT(*)`` over ``webhook_deliveries``
therefore measures only this example's emit, with no leakage from
prior examples.

Session management
------------------

The shared ``conftest.db_session`` fixture wraps the test in
``async with session.begin() as transaction:`` and rolls back at
teardown. That pattern is incompatible with a property test that
needs to commit between phases (subscription insert → emit → query)
across many Hypothesis examples: the first commit closes the
wrapper and the second example then trips
``InvalidRequestError: Can't operate on closed transaction inside
context manager`` on the next session operation. To avoid that
brittleness we build a per-test session factory bound to the
function-scoped ``test_engine`` and open a fresh session per phase,
mirroring the pattern established in
:mod:`tests.test_property_webhook_subscription_audit_emission`.

This file does not need a per-test HTTP client because the property
exercises ``emit_webhook_event`` directly rather than through any
route. The emitter is the single entry point for fan-out (per its
module docstring), so calling it is the most direct surface for
Property 8.

# Feature: api-platform-export, Property 8: Webhook routing fan-out
# Validates: Requirement 4.1
"""

from __future__ import annotations

import uuid
from typing import FrozenSet, List, Optional, Tuple

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings, strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.core.webhook_secret_crypto import encrypt_signing_secret
from app.models.survey import Survey
from app.models.survey_permission import SurveyPermission
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_subscription import WebhookSubscription
from app.services.webhook_emitter import emit_webhook_event


# ── Constants ─────────────────────────────────────────────────────────

#: Canonical event type set for the webhook subsystem. Pinning the
#: literals here keeps the strategy honest if the supported set ever
#: drifts in :mod:`app.api.v1.webhooks`; the assertion in
#: :func:`test_p8_event_types_match_supported_set` would surface the
#: drift before the property test fires.
_EVENT_TYPES: Tuple[str, ...] = (
    "response.created",
    "response.completed",
    "quota.reached",
    "distribution.sent",
)


# ── Strategies ────────────────────────────────────────────────────────

# Each subscription is described by ``(active, event_types,
# survey_scope)``. ``event_types`` is a subset (possibly empty) of the
# canonical event set; ``survey_scope`` is either the literal
# ``"survey_a"`` (resolved to the example's only survey at insert time)
# or :data:`None` for an account-scoped subscription that matches every
# survey the owner can see.
_SUB_SPEC: st.SearchStrategy[Tuple[bool, FrozenSet[str], Optional[str]]] = st.tuples(
    st.booleans(),
    st.sets(st.sampled_from(_EVENT_TYPES), min_size=0, max_size=len(_EVENT_TYPES)),
    st.sampled_from(["survey_a", None]),
)

# 1..5 subscriptions per example. Below 1 we would have nothing to
# match against; above 5 the per-example DB write cost outweighs the
# extra coverage at the property's cardinality.
_SUB_SPECS: st.SearchStrategy[
    List[Tuple[bool, FrozenSet[str], Optional[str]]]
] = st.lists(_SUB_SPEC, min_size=1, max_size=5)

_CHOSEN_EVENT: st.SearchStrategy[str] = st.sampled_from(_EVENT_TYPES)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def p8_session_factory(test_engine) -> async_sessionmaker:
    """Build a session factory bound to the function-scoped test engine.

    Each call to the factory yields a fresh :class:`AsyncSession` with
    no outer ``session.begin()`` wrapper, so commits between phases
    (subscription insert → emit → query) succeed without invalidating
    later operations across Hypothesis examples (see module docstring).

    ``expire_on_commit=False`` mirrors the production session factory
    so attribute access on inserted rows after commit behaves the same
    way the route layer does.
    """
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )


# ── Helpers ───────────────────────────────────────────────────────────


async def _make_owner_with_survey(
    session_factory: async_sessionmaker,
) -> Tuple[str, str]:
    """Insert an owner, a survey, and a viewer permission for the owner.

    The owner's email carries a per-call uuid so two examples cannot
    collide on the unique-email constraint. The survey is owned by the
    owner; the permission row grants the owner ``viewer`` on the
    survey. The emitter's permission gate (see
    :func:`app.services.webhook_emitter.emit_webhook_event`) only
    checks for the existence of a ``SurveyPermission`` row on
    ``(survey_id, user_id)``; any role qualifies.

    Args:
        session_factory: The per-test session factory.

    Returns:
        ``(owner_id, survey_id)`` for use by the rest of the example.
    """
    async with session_factory() as session:
        owner = User(
            email=f"p8-fanout-{uuid.uuid4().hex[:12]}@example.com",
            hashed_password=hash_password("Test1234!"),
            display_name="P8 Owner",
        )
        session.add(owner)
        await session.flush()

        survey = Survey(owner_id=owner.id, title="P8 Survey")
        session.add(survey)
        await session.flush()

        permission = SurveyPermission(
            user_id=owner.id, survey_id=survey.id, role="viewer"
        )
        session.add(permission)
        await session.commit()
        return owner.id, survey.id


async def _insert_subscriptions(
    session_factory: async_sessionmaker,
    owner_id: str,
    survey_a_id: str,
    specs: List[Tuple[bool, FrozenSet[str], Optional[str]]],
) -> List[str]:
    """Persist one ``WebhookSubscription`` row per spec triple.

    The ``signing_secret_ciphertext`` column is required by the model
    so we mint a per-row Fernet ciphertext from a placeholder
    plaintext. Property 8 does not exercise the signing surface; the
    ciphertext is irrelevant to fan-out and exists only to satisfy
    the NOT NULL constraint.

    Args:
        session_factory: The per-test session factory.
        owner_id: The owning user's id.
        survey_a_id: The example's only survey id; used to resolve a
            ``"survey_a"`` scope token to the actual survey id.
        specs: List of ``(active, event_types, survey_scope)`` triples.
            ``event_types`` is sorted before insert so the JSONB column
            value is deterministic across runs (helpful when debugging
            a falsifying example by hand).

    Returns:
        Subscription ids in the order the specs were given.
    """
    sub_ids: List[str] = []
    async with session_factory() as session:
        for active, event_types, survey_scope in specs:
            survey_id = survey_a_id if survey_scope == "survey_a" else None
            subscription = WebhookSubscription(
                user_id=owner_id,
                survey_id=survey_id,
                target_url="https://hooks.example.com/p8",
                event_types=sorted(event_types),
                signing_secret_ciphertext=encrypt_signing_secret(
                    f"whsec_{uuid.uuid4().hex[:24]}"
                ),
                active=active,
            )
            session.add(subscription)
            await session.flush()
            sub_ids.append(subscription.id)
        await session.commit()
    return sub_ids


def _predict_match_count(
    specs: List[Tuple[bool, FrozenSet[str], Optional[str]]],
    chosen_event: str,
) -> int:
    """Compute the expected matching-subscription count for one emit.

    Implements the routing predicate restricted to one owner whose
    permission on the target survey is held constant. The owner's
    ``viewer`` permission is always satisfied (see
    :func:`_make_owner_with_survey`), so the predicate reduces to::

        active AND chosen_event in event_types
        AND (survey_scope is None OR survey_scope == "survey_a")

    The disjunction inside the parenthesis is always true for the
    spec generator, because ``survey_scope`` is sampled from
    ``["survey_a", None]`` and the emitted event is always against
    ``survey_a``. The disjunction is kept explicit anyway so that a
    later strategy edit that introduces a third scope token does not
    silently break the prediction.

    Args:
        specs: List of ``(active, event_types, survey_scope)`` triples
            as inserted into the database.
        chosen_event: The event type emitted in this Hypothesis
            example.

    Returns:
        Expected count of newly created ``WebhookDelivery`` rows.
    """
    count = 0
    for active, event_types, survey_scope in specs:
        if not active:
            continue
        if chosen_event not in event_types:
            continue
        if survey_scope is not None and survey_scope != "survey_a":
            continue
        count += 1
    return count


async def _count_deliveries(session_factory: async_sessionmaker) -> int:
    """Return the global ``COUNT(*)`` over ``webhook_deliveries``.

    Used to compute the pre/post delta for the example. Cross-example
    rows do not contribute to the delta because the emitter's
    candidate set excludes prior owners' subscriptions (their
    permissions and survey ids do not match the current example).

    Args:
        session_factory: The per-test session factory.

    Returns:
        Total row count in ``webhook_deliveries``.
    """
    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(WebhookDelivery)
        )
        return int(result.scalar_one())


# ── Pre-flight invariant on the strategy ──────────────────────────────


# Feature: api-platform-export, Property 8: Webhook routing fan-out
# Validates: Requirement 4.1
def test_p8_event_types_match_supported_set() -> None:
    """The strategy's event-type set equals the route's supported set.

    A regression that drops or renames an event type in
    :mod:`app.api.v1.webhooks` would silently make this test exercise
    a stale event set. Pinning the registry import here surfaces the
    drift before the property test fires.
    """
    from app.api.v1.webhooks import SUPPORTED_EVENT_TYPES

    assert set(_EVENT_TYPES) == set(SUPPORTED_EVENT_TYPES), (
        f"strategy event set {sorted(_EVENT_TYPES)!r} drifted from "
        f"route-level set {sorted(SUPPORTED_EVENT_TYPES)!r}"
    )


# ── The property test ─────────────────────────────────────────────────


# Feature: api-platform-export, Property 8: Webhook routing fan-out
# Validates: Requirement 4.1
@pytest.mark.asyncio
@given(specs=_SUB_SPECS, chosen_event=_CHOSEN_EVENT)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p8_webhook_routing_fanout(
    p8_session_factory: async_sessionmaker,
    specs: List[Tuple[bool, FrozenSet[str], Optional[str]]],
    chosen_event: str,
) -> None:
    """Fan-out creates one delivery per matching subscription.

    Sub-invariants asserted in lock-step:

    * The number of new ``WebhookDelivery`` rows (post-emit total
      minus pre-emit total) equals the predicted match count.
    * The list of delivery ids returned by
      :func:`emit_webhook_event` has the same length as the
      delta. A divergence here would mean the emitter inserted
      rows it did not return, or returned ids for rows it did
      not insert — both regressions would otherwise slip past the
      enqueue path.

    Validates: Requirement 4.1.
    """
    owner_id, survey_id = await _make_owner_with_survey(p8_session_factory)
    sub_ids = await _insert_subscriptions(
        p8_session_factory, owner_id, survey_id, specs
    )
    assert len(sub_ids) == len(specs)

    predicted = _predict_match_count(specs, chosen_event)

    pre_count = await _count_deliveries(p8_session_factory)

    async with p8_session_factory() as session:
        delivery_ids = await emit_webhook_event(
            session,
            event_type=chosen_event,
            survey_id=survey_id,
            payload={"event": "p8-fanout", "marker": uuid.uuid4().hex},
        )
        await session.commit()

    post_count = await _count_deliveries(p8_session_factory)
    actual_new = post_count - pre_count

    assert actual_new == predicted, (
        "fan-out delivery count mismatch: "
        f"predicted={predicted}, actual_new={actual_new}, "
        f"pre={pre_count}, post={post_count}, "
        f"specs={specs!r}, chosen_event={chosen_event!r}"
    )
    assert len(delivery_ids) == predicted, (
        "emit_webhook_event returned wrong delivery-id count: "
        f"predicted={predicted}, returned={len(delivery_ids)}, "
        f"specs={specs!r}, chosen_event={chosen_event!r}"
    )

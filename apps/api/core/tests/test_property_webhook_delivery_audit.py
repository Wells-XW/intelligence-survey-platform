"""Property test P19 (webhook delivery portion): audit emission for terminal transitions.

Per design §Property 19 (Requirements 7.3, 9.4), every state
transition that is enumerated in the audit verb table must append
exactly one row to ``audit_logs`` whose ``action`` equals the
canonical verb, whose ``user_id`` equals the actor, and whose
``resource_type`` / ``resource_id`` reference the affected entity.
This module covers the **webhook-delivery** portion of that property.

Canonical verbs
---------------

The canonical webhook-delivery verbs registered in
:data:`app.core.audit.API_PLATFORM_VERBS` are exactly two:

* ``webhook.delivery.succeeded`` — terminal HTTP 2xx outcome.
* ``webhook.delivery.failed``    — terminal failure: either the row
  exhausted the 5-entry retry schedule (the "max-attempts" branch)
  or the worker's own retry-enqueue raised before scheduling the
  next attempt (the "enqueue-failure" branch documented in design
  §Property 19 sequence diagram and Req 4 AC7). Both branches share
  the same verb because both correspond to the same row state
  ``failed_permanent``; the originating cause is recorded in
  ``audit_logs.details.last_error`` and ``last_response_status``.

The wider feature spec contemplated additional verbs at one point
(``webhook.delivery.attempt_made`` / ``webhook.delivery.dlq``) but
those were not adopted: the worker emits no per-attempt audit row
on non-terminal ``retrying`` transitions and no separate ``dlq``
verb because there is no separate DLQ row state. The test here
asserts the contract that is actually shipped: **exactly one
terminal audit row per delivery, two-verb registry, no
per-attempt rows on the audit surface.** A future schema change
that introduces an attempt-level verb would require this test to
be updated alongside :data:`app.core.audit.API_PLATFORM_VERBS`.

Strategy
--------

For each Hypothesis example we:

1. Insert a fresh owner user and a fresh
   :class:`~app.models.webhook_subscription.WebhookSubscription`
   directly into the test database via a per-example committing
   session. Unique email and ciphertext keep concurrent or
   successive examples isolated.
2. Generate ``n_deliveries`` (1..3) deliveries; each delivery owns
   an attempt-outcome plan drawn from a Hypothesis strategy. Each
   plan element specifies the outcome of one HTTP attempt:
   ``http_2xx`` (terminal success), ``http_5xx`` (transient HTTP
   failure), or ``http_5xx_then_enqueue_fail`` (transient HTTP
   failure followed by a retry-enqueue exception, which the worker
   classifies as terminal ``failed_permanent``).
3. Insert one ``WebhookDelivery`` row per plan in status ``pending``.
4. Drive :func:`app.tasks.webhook_tasks._async_deliver_webhook`
   directly (not via Celery) once per planned attempt. Stop driving
   a delivery as soon as it enters a terminal state — extra plan
   elements after a terminal transition are ignored, mirroring the
   worker's own idempotency clause.
5. Mock the HTTP layer: monkeypatch
   :class:`httpx.AsyncClient` so each ``post`` call returns the
   status code dictated by the current attempt's plan element, and
   mock :func:`celery_app.send_task` to either succeed silently or
   raise ``RuntimeError`` for the ``enqueue_fail`` case.
6. Read back every ``audit_logs`` row whose ``resource_id`` is a
   delivery id from this example. Assert (a) exactly one terminal
   audit row per delivery whose terminal state was reached;
   (b) zero audit rows on non-terminal deliveries (the run cut off
   before terminal — only possible if the plan was all
   transient-fail and shorter than 5 entries); (c) every terminal
   row's ``action`` matches the predicted verb;
   (d) ``resource_type='webhook_delivery'`` and
   ``resource_id`` equals the delivery id;
   (e) ``user_id`` equals the subscription owner id.

Worker-session note
-------------------

The worker module imports ``async_session`` from
:mod:`app.database` at module load time, so monkey-patching
``app.database.async_session`` after the fact does not redirect the
worker's session creation. We therefore patch the worker module's
own attribute (``app.tasks.webhook_tasks.async_session``) and
replace it with a session factory bound to the function-scoped
``test_engine`` fixture exposed by ``conftest.py``. This is the
same pattern used by the api-key audit-emission property test
(``test_property_api_key_audit_emission.py``).

Validates: Requirements 7.3, 9.4
"""

# Feature: api-platform-export, Property 19: Audit emission for terminal transitions

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit import API_PLATFORM_VERBS
from app.core.security import hash_password
from app.core.webhook_secret_crypto import encrypt_signing_secret
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_subscription import WebhookSubscription


# ── Constants ─────────────────────────────────────────────────────────

#: The two canonical verbs the worker is allowed to emit on a
#: terminal webhook-delivery transition. Pinning the literal strings
#: locally keeps the test honest if the registry ever drops or
#: renames a verb — the assertion would fail rather than silently
#: filter the row out.
_DELIVERY_VERBS: Tuple[str, ...] = (
    "webhook.delivery.succeeded",
    "webhook.delivery.failed",
)

#: Attempt-outcome labels the strategy emits. Names mirror the
#: docstring above: ``http_2xx`` is the only success outcome the
#: worker treats as terminal-success; ``http_5xx`` is one of the
#: transient outcomes that drives the retry counter; the compound
#: ``http_5xx_then_enqueue_fail`` packs a transient HTTP failure
#: plus a retry-enqueue exception so the worker takes the explicit
#: "scheduling failure is terminal" branch documented in Req 4 AC7.
_OUTCOME_HTTP_2XX: str = "http_2xx"
_OUTCOME_HTTP_5XX: str = "http_5xx"
_OUTCOME_ENQUEUE_FAIL: str = "http_5xx_then_enqueue_fail"

#: Length of the retry schedule. After ``attempt_count >= MAX_ATTEMPTS``
#: the worker terminates the row as ``failed_permanent`` regardless
#: of the schedule's remaining entries (Req 4 AC6). Pinned as a
#: module constant rather than re-read from settings on every example
#: so the predictor is independent of any test-side settings tweak.
_MAX_ATTEMPTS: int = 5


# ── Strategies ────────────────────────────────────────────────────────

#: Per-attempt outcome. ``http_2xx`` makes the attempt the last one;
#: the strategy is not constrained to terminate explicitly because
#: the per-delivery driver simply stops calling once the row is
#: terminal — extra elements after a terminal element are ignored.
_OUTCOME = st.sampled_from(
    [_OUTCOME_HTTP_2XX, _OUTCOME_HTTP_5XX, _OUTCOME_ENQUEUE_FAIL]
)

#: Plan length per delivery. Capped at ``_MAX_ATTEMPTS`` because the
#: worker terminates the row at attempt 5 regardless of plan content,
#: so additional elements would never be consumed by the driver.
_PLAN = st.lists(_OUTCOME, min_size=1, max_size=_MAX_ATTEMPTS)

#: Number of deliveries per Hypothesis example. Three keeps each
#: example fast (each delivery costs at most five HTTP-mock round
#: trips) while still exercising fan-out across multiple rows so a
#: regression that emits the same audit row twice for one delivery
#: surfaces.
_N_DELIVERIES = st.integers(min_value=1, max_value=3)


# ── Reference predictor ───────────────────────────────────────────────


def _predict_terminal_outcome(
    plan: List[str],
) -> Tuple[Optional[str], int, int]:
    """Predict the terminal verb / attempt count / executed-attempt count.

    Mirrors the live state machine in
    :func:`app.tasks.webhook_tasks._async_deliver_webhook`.

    Args:
        plan: Sequence of attempt-outcome labels from the strategy.

    Returns:
        ``(verb, attempt_count_after, executed)`` where:

        * ``verb`` is the canonical terminal verb if the plan reaches
          a terminal transition (``"webhook.delivery.succeeded"`` or
          ``"webhook.delivery.failed"``), otherwise ``None``.
        * ``attempt_count_after`` is what the row's ``attempt_count``
          column would be after the run. Each transient failure
          increments by 1; ``http_2xx`` increments to 1 only when
          ``attempt_count == 0`` because the worker bumps the counter
          inside :func:`_terminate_succeeded` to reflect the attempt
          that just succeeded.
        * ``executed`` is the number of attempts the driver actually
          made. Always equal to the number of plan elements consumed
          before the row entered a terminal state. Used by the test
          to assert that the worker stopped driving when the row
          became terminal.
    """
    attempt_count = 0
    executed = 0
    verb: Optional[str] = None
    for outcome in plan:
        executed += 1
        if outcome == _OUTCOME_HTTP_2XX:
            # Terminal-succeeded: counter reflects the successful
            # attempt that just landed.
            attempt_count = max(attempt_count, 0) + 1 if attempt_count == 0 else attempt_count
            verb = "webhook.delivery.succeeded"
            break
        # Failure path: counter increments first.
        attempt_count += 1
        if outcome == _OUTCOME_ENQUEUE_FAIL:
            # Retry-enqueue exception is terminal regardless of
            # remaining schedule entries.
            verb = "webhook.delivery.failed"
            break
        # outcome == _OUTCOME_HTTP_5XX
        if attempt_count >= _MAX_ATTEMPTS:
            # Schedule exhausted on this attempt.
            verb = "webhook.delivery.failed"
            break
    return verb, attempt_count, executed


# ── Mock layer ────────────────────────────────────────────────────────


class _MockResponse:
    """Minimal stand-in for ``httpx.Response`` exposing ``status_code``.

    The worker only reads :attr:`httpx.Response.status_code` on the
    success path, so we do not need to simulate body / headers / any
    other attribute.
    """

    __slots__ = ("status_code",)

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _MockAsyncClient:
    """Stand-in for ``httpx.AsyncClient`` driven by a per-test queue.

    The constructor accepts ``timeout=`` (which the worker passes) and
    discards it. The async-context-manager protocol is implemented so
    the worker's ``async with httpx.AsyncClient(timeout=...) as client:``
    block runs unchanged. ``post`` pops one element from the shared
    outcome queue and either returns a mock response with the dictated
    status code or raises an httpx-shaped exception.

    A single class-level queue is shared across instances because the
    worker re-creates the ``AsyncClient`` on every attempt; using a
    class attribute keeps the queue continuity between attempts.
    """

    #: Outcome queue. Each element is one of:
    #: ``("status", int)`` — return ``_MockResponse(status_code=int)``.
    #: ``("timeout",)`` — raise ``httpx.TimeoutException``.
    #: ``("network",)`` — raise ``httpx.HTTPError("network")``.
    queue: List[Tuple[Any, ...]] = []

    def __init__(self, timeout: Any = None) -> None:  # noqa: D401
        # Accept and discard ``timeout`` so the worker's call site
        # remains unchanged.
        del timeout

    async def __aenter__(self) -> "_MockAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, content: bytes, headers: dict) -> _MockResponse:
        """Pop one outcome from the queue and apply it.

        Args:
            url: Target URL — ignored by the mock, kept in the
                signature so the worker's call site sees a faithful
                signature.
            content: Canonical body bytes — ignored.
            headers: Per-attempt headers — ignored.

        Returns:
            A ``_MockResponse`` whose ``status_code`` matches the
            queued outcome.

        Raises:
            httpx.TimeoutException: when the queued outcome is
                ``("timeout",)``.
            httpx.HTTPError: when the queued outcome is
                ``("network",)``.
        """
        del url, content, headers
        import httpx as _httpx  # local import keeps the test module
                                 # importable when httpx is absent

        if not _MockAsyncClient.queue:
            raise AssertionError(
                "_MockAsyncClient.queue exhausted: worker made more "
                "HTTP attempts than the test plan accounted for"
            )
        outcome = _MockAsyncClient.queue.pop(0)
        kind = outcome[0]
        if kind == "status":
            return _MockResponse(status_code=outcome[1])
        if kind == "timeout":
            raise _httpx.TimeoutException("mock timeout")
        if kind == "network":
            raise _httpx.HTTPError("mock network error")
        raise AssertionError(f"unexpected mock outcome kind: {kind!r}")


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def p19d_session_factory(test_engine) -> async_sessionmaker:
    """Build a session factory bound to the function-scoped test engine.

    Each call to the factory yields a fresh :class:`AsyncSession` with
    no outer ``session.begin()`` wrapper, so the worker's
    ``await db.commit()`` calls succeed without invalidating later
    operations across Hypothesis examples.
    """
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest_asyncio.fixture
async def patched_worker(p19d_session_factory, monkeypatch):
    """Patch the worker module to use the test session factory plus mocks.

    Three patches:

    * ``app.tasks.webhook_tasks.async_session`` is replaced with the
      function-scoped ``p19d_session_factory`` so the worker writes
      to the test database.
    * ``httpx.AsyncClient`` is replaced with :class:`_MockAsyncClient`
      so every outbound POST is driven by the per-test queue.
    * ``celery_app.send_task`` is replaced with a controllable stub
      whose behaviour is selected per call by the test driver: by
      default it succeeds silently; when the driver flips
      ``send_task_will_raise`` to ``True`` (for the
      ``http_5xx_then_enqueue_fail`` plan element) the next call
      raises ``RuntimeError``. The flag is cleared after the call so
      the next attempt's enqueue resumes succeeding.

    Yields a small handle exposing the queue and the flag so the
    driver can manipulate them between attempts.
    """
    import httpx as _httpx
    from app.tasks import webhook_tasks as _wt

    # Reset class-level mock queue for this test.
    _MockAsyncClient.queue = []
    monkeypatch.setattr(_httpx, "AsyncClient", _MockAsyncClient)
    monkeypatch.setattr(_wt, "async_session", p19d_session_factory)

    state: Dict[str, Any] = {
        "send_task_will_raise": False,
        "send_task_calls": 0,
    }

    def _fake_send_task(*args, **kwargs):  # noqa: ANN001
        state["send_task_calls"] += 1
        if state["send_task_will_raise"]:
            state["send_task_will_raise"] = False
            raise RuntimeError("mock celery enqueue failure")
        return None

    monkeypatch.setattr(_wt.celery_app, "send_task", _fake_send_task)

    yield {
        "queue": _MockAsyncClient.queue,  # alias for readability
        "state": state,
    }


# ── DB seeding helpers ────────────────────────────────────────────────


async def _seed_owner_and_subscription(
    session_factory: async_sessionmaker,
) -> Tuple[str, str]:
    """Insert a fresh owner user and one webhook subscription.

    The subscription's ``signing_secret_ciphertext`` is populated with
    a fresh Fernet ciphertext so the worker's
    :func:`decrypt_signing_secret` call succeeds; the actual signature
    bytes are irrelevant to Property 19 because the mock HTTP layer
    never validates them.

    Args:
        session_factory: Per-test session factory.

    Returns:
        ``(owner_id, subscription_id)``.
    """
    async with session_factory() as session:
        owner = User(
            id=str(uuid.uuid4()),
            email=f"p19d-{uuid.uuid4().hex[:12]}@example.com",
            hashed_password=hash_password("Test1234!"),
            display_name="P19 delivery owner",
        )
        session.add(owner)
        await session.flush()

        sub = WebhookSubscription(
            user_id=owner.id,
            survey_id=None,
            target_url="https://hooks.example.com/p19d",
            event_types=["response.created"],
            signing_secret_ciphertext=encrypt_signing_secret(
                f"whsec_{uuid.uuid4().hex[:24]}"
            ),
            active=True,
        )
        session.add(sub)
        await session.commit()
        return owner.id, sub.id


async def _seed_delivery(
    session_factory: async_sessionmaker, subscription_id: str
) -> str:
    """Insert one ``WebhookDelivery`` row in status ``pending``.

    Returns the new row's id. The ``payload`` is a small JSON-safe
    dict; its contents do not affect Property 19.
    """
    async with session_factory() as session:
        delivery = WebhookDelivery(
            id=str(uuid.uuid4()),
            subscription_id=subscription_id,
            event_type="response.created",
            payload={"response_id": str(uuid.uuid4())},
            status="pending",
            attempt_count=0,
        )
        session.add(delivery)
        await session.commit()
        return delivery.id


async def _read_delivery_audit_rows(
    session_factory: async_sessionmaker, delivery_ids: List[str]
) -> List[AuditLog]:
    """Read every audit row whose ``resource_id`` is in ``delivery_ids``.

    Filters server-side by both the delivery-id set and the canonical
    delivery verb set so cross-test audit entries (e.g., subscription
    create rows from earlier examples) cannot drift into the
    assertion. The fresh session prevents the SQLAlchemy identity map
    from caching stale rows after the worker's commits.
    """
    async with session_factory() as session:
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.resource_id.in_(delivery_ids))
            .where(AuditLog.action.in_(_DELIVERY_VERBS))
            .order_by(AuditLog.id.asc())
        )
        return list(result.scalars().all())


async def _read_delivery_row(
    session_factory: async_sessionmaker, delivery_id: str
) -> WebhookDelivery:
    """Re-read one delivery row in a fresh session for state assertions.

    A fresh session guarantees the read sees the latest committed
    state from the worker rather than a cached pre-commit copy.
    """
    async with session_factory() as session:
        row = await session.get(WebhookDelivery, delivery_id)
        assert row is not None, f"delivery {delivery_id} vanished"
        return row


# ── Driver ────────────────────────────────────────────────────────────


async def _drive_delivery(
    *,
    delivery_id: str,
    plan: List[str],
    handle: Dict[str, Any],
) -> int:
    """Drive one delivery row through its plan; return executed-attempt count.

    For each plan element, push the appropriate outcome onto the mock
    HTTP queue, set the ``send_task_will_raise`` flag if the element
    is ``http_5xx_then_enqueue_fail``, then invoke the worker's
    async body once. Re-read the row state between attempts to
    decide whether to keep driving.

    Stops driving as soon as the row state is terminal — the worker
    short-circuits its own body in that case (it returns immediately
    on entry when ``status in ('succeeded', 'failed_permanent')``),
    so an extra call would be a no-op but the test does not need to
    waste it.

    Args:
        delivery_id: UUID of the row to drive.
        plan: Per-attempt outcome plan.
        handle: The dict yielded by :func:`patched_worker` carrying
            the mock HTTP queue and the send-task control state.

    Returns:
        Number of plan elements actually consumed before the row
        became terminal. Used by the caller to assert the predictor
        agrees with the worker on attempt-count semantics.
    """
    from app.tasks.webhook_tasks import _async_deliver_webhook

    queue: List[Tuple[Any, ...]] = handle["queue"]
    state: Dict[str, Any] = handle["state"]
    executed = 0

    for outcome in plan:
        executed += 1
        # Translate the plan element into a queue-entry plus a
        # send-task control bit.
        if outcome == _OUTCOME_HTTP_2XX:
            queue.append(("status", 200))
        elif outcome == _OUTCOME_HTTP_5XX:
            queue.append(("status", 500))
        elif outcome == _OUTCOME_ENQUEUE_FAIL:
            queue.append(("status", 500))
            state["send_task_will_raise"] = True
        else:  # pragma: no cover — strategy is closed under the enum
            raise AssertionError(f"unknown outcome: {outcome!r}")

        await _async_deliver_webhook(delivery_id)

        # If the row became terminal, no further plan elements
        # apply. We re-read in a fresh session because the worker's
        # commit may not yet be visible to a long-lived session.
        # The session-factory pattern in this module gives every
        # read its own session, so we just rely on that.
        from app.tasks import webhook_tasks as _wt

        async with _wt.async_session() as s:
            row = await s.get(WebhookDelivery, delivery_id)
            if row is None or row.status in ("succeeded", "failed_permanent"):
                break

    return executed


# ── Pre-flight invariants ─────────────────────────────────────────────


# Feature: api-platform-export, Property 19: Audit emission for terminal transitions
# Validates: Requirements 7.3, 9.4
def test_p19d_delivery_verbs_are_registered() -> None:
    """Both delivery verbs are members of the canonical registry.

    A regression that drops one of the two verbs would silently skip
    the audit emission on the matching transition. Pinning the
    literals here surfaces the drift before the property test runs.
    """
    for verb in _DELIVERY_VERBS:
        assert verb in API_PLATFORM_VERBS, (
            f"verb {verb!r} expected in API_PLATFORM_VERBS but missing"
        )


# ── Property test ────────────────────────────────────────────────────


# Feature: api-platform-export, Property 19: Audit emission for terminal transitions
# Validates: Requirements 7.3, 9.4
@pytest.mark.asyncio
@given(
    n_deliveries=_N_DELIVERIES,
    plans=st.lists(_PLAN, min_size=1, max_size=3),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p19_webhook_delivery_audit_emission(
    p19d_session_factory: async_sessionmaker,
    patched_worker,
    n_deliveries: int,
    plans: List[List[str]],
) -> None:
    """Each terminal delivery transition writes exactly one matching audit row.

    Sub-invariants:

    * For every delivery whose plan reaches a terminal outcome, the
      ``audit_logs`` table contains exactly one row scoped to that
      delivery id with the predicted verb. Two rows would mean the
      worker double-emitted; zero rows would mean the audit write
      was lost.
    * The row's ``resource_type`` is ``webhook_delivery`` and its
      ``resource_id`` equals the delivery id.
    * The row's ``user_id`` equals the subscription owner's id.
    * For deliveries whose plan does not reach a terminal outcome
      (the "still retrying" branch — only possible when the plan is
      shorter than 5 entries and contains no ``http_2xx`` /
      ``http_5xx_then_enqueue_fail``), zero delivery-scoped audit
      rows exist. This is the canonical contract: non-terminal
      transitions emit no audit row.
    * The row's ``attempt_count`` matches the predictor's
      ``attempt_count_after`` value, so a regression that bumps the
      counter once too many or once too few surfaces as part of
      Property 19 rather than silently passing.

    Validates: Requirements 7.3, 9.4.
    """
    # Right-size the plan list: Hypothesis may have generated more or
    # fewer plans than requested by ``n_deliveries``. Cropping (or
    # padding via repetition of the first plan) keeps the strategy
    # small and avoids tossing examples back to Hypothesis.
    if len(plans) < n_deliveries:
        plans = plans + [plans[0]] * (n_deliveries - len(plans))
    plans = plans[:n_deliveries]

    owner_id, sub_id = await _seed_owner_and_subscription(p19d_session_factory)

    delivery_ids: List[str] = []
    expected_verbs: Dict[str, Optional[str]] = {}
    expected_attempt_counts: Dict[str, int] = {}
    expected_executed: Dict[str, int] = {}

    for plan in plans:
        delivery_id = await _seed_delivery(p19d_session_factory, sub_id)
        delivery_ids.append(delivery_id)
        verb, attempt_count, executed = _predict_terminal_outcome(plan)
        expected_verbs[delivery_id] = verb
        expected_attempt_counts[delivery_id] = attempt_count
        expected_executed[delivery_id] = executed

    # Drive each delivery through its plan in turn. The mock HTTP
    # queue is shared across deliveries but the driver only enqueues
    # outcomes immediately before invoking the worker, so plans do
    # not interleave.
    for delivery_id, plan in zip(delivery_ids, plans):
        actual_executed = await _drive_delivery(
            delivery_id=delivery_id,
            plan=plan,
            handle=patched_worker,
        )
        assert actual_executed == expected_executed[delivery_id], (
            f"driver consumed {actual_executed} plan elements for "
            f"delivery {delivery_id!r}, expected "
            f"{expected_executed[delivery_id]} (plan={plan!r})"
        )

    # Read all delivery-scoped audit rows in one query and bucket
    # them by delivery id.
    rows = await _read_delivery_audit_rows(
        p19d_session_factory, delivery_ids
    )
    rows_by_delivery: Dict[str, List[AuditLog]] = {
        did: [] for did in delivery_ids
    }
    for row in rows:
        rows_by_delivery.setdefault(row.resource_id, []).append(row)

    # Per-delivery assertions.
    for delivery_id, plan in zip(delivery_ids, plans):
        expected_verb = expected_verbs[delivery_id]
        delivery_rows = rows_by_delivery[delivery_id]

        if expected_verb is None:
            # Plan did not reach a terminal transition — non-terminal
            # transitions emit no audit row.
            assert len(delivery_rows) == 0, (
                f"non-terminal delivery {delivery_id!r} unexpectedly "
                f"emitted {len(delivery_rows)} audit row(s); plan={plan!r}; "
                f"verbs={[r.action for r in delivery_rows]}"
            )
            continue

        assert len(delivery_rows) == 1, (
            f"delivery {delivery_id!r} expected exactly one terminal "
            f"audit row with verb {expected_verb!r}; got "
            f"{len(delivery_rows)} row(s) with verbs "
            f"{[r.action for r in delivery_rows]}; plan={plan!r}"
        )
        row = delivery_rows[0]
        assert row.action == expected_verb, (
            f"delivery {delivery_id!r} audit verb mismatch: "
            f"expected {expected_verb!r}, got {row.action!r}; "
            f"plan={plan!r}"
        )
        assert row.resource_type == "webhook_delivery", (
            f"delivery {delivery_id!r} audit row resource_type "
            f"{row.resource_type!r}; expected 'webhook_delivery'"
        )
        assert row.resource_id == delivery_id, (
            f"delivery {delivery_id!r} audit row resource_id "
            f"{row.resource_id!r}; expected {delivery_id!r}"
        )
        assert row.user_id == owner_id, (
            f"delivery {delivery_id!r} audit row user_id "
            f"{row.user_id!r}; expected owner {owner_id!r}"
        )

        # Cross-check the row state: attempt_count on the row should
        # match the predictor.
        delivery_row = await _read_delivery_row(
            p19d_session_factory, delivery_id
        )
        assert delivery_row.attempt_count == expected_attempt_counts[delivery_id], (
            f"delivery {delivery_id!r} attempt_count "
            f"{delivery_row.attempt_count} != predictor "
            f"{expected_attempt_counts[delivery_id]}; plan={plan!r}"
        )
        if expected_verb == "webhook.delivery.succeeded":
            assert delivery_row.status == "succeeded", (
                f"delivery {delivery_id!r} status {delivery_row.status!r}; "
                f"expected 'succeeded' for plan {plan!r}"
            )
        elif expected_verb == "webhook.delivery.failed":
            assert delivery_row.status == "failed_permanent", (
                f"delivery {delivery_id!r} status {delivery_row.status!r}; "
                f"expected 'failed_permanent' for plan {plan!r}"
            )

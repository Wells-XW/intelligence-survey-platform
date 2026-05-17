"""Property test P10: Webhook delivery state machine.

Per design §Property 10 (Requirements 4.4, 4.5, 4.6, 4.7, 4.8), the
:func:`app.tasks.webhook_tasks.deliver_webhook` worker drives a
:class:`app.models.webhook_delivery.WebhookDelivery` row through a
constrained state machine whose persisted columns
(``status`` and ``attempt_count``) at every step must agree with a
reference machine evaluated on the same outcome sequence. The
implementation states are:

* ``pending`` — initial state on insert.
* ``retrying`` — set after a non-success attempt with retries
  remaining and a successful broker enqueue of the next attempt.
* ``succeeded`` — terminal: an HTTP 2xx response was received on
  some attempt.
* ``failed_permanent`` — terminal: either the fifth attempt failed
  (Req 4.6) or the broker enqueue of the next retry itself failed
  (Req 4.7).

This test does NOT distinguish between transient and permanent HTTP
failures because the worker treats them identically: both feed the
shared retry-or-terminate branch. The 503 / 410 split in the action
strategy below is kept only for parity with the original test brief
and to ensure both status codes drive the same state-machine
behaviour.

Strategy
--------

For every Hypothesis example we:

1. Insert a fresh owner, a webhook subscription, and one
   ``WebhookDelivery`` row in ``pending`` state. Per-example unique
   identifiers (UUID-suffixed email and a UUID delivery id) keep
   accumulated state from prior examples on the function-scoped
   engine from contaminating later assertions.
2. Generate a sequence of 1..7 actions drawn from
   ``{success, transient_fail, permanent_fail, enqueue_failure}``.
   The first three drive the ``httpx.AsyncClient.post`` mock to
   return a 200, 503, or 410 status code respectively; the fourth
   drives the ``httpx`` mock to return 503 *and* makes
   ``celery_app.send_task`` raise so the worker's retry-enqueue
   path fails. Including ``enqueue_failure`` directly exercises
   Req 4.7 (retry scheduling failure terminates the delivery).
3. For each action, drive the worker by calling
   :func:`app.tasks.webhook_tasks._async_deliver_webhook`
   synchronously. The task's public Celery wrapper wraps this body
   in :func:`asyncio.run`, which would deadlock under
   ``pytest-asyncio``; calling the underlying coroutine directly is
   semantically equivalent and the only safe option from inside the
   running test loop.
4. After each call, re-read the delivery row in a fresh session and
   assert that ``(status, attempt_count)`` equals the reference
   machine's prediction. Also assert that the observed transition
   from the previous persisted state is in the allowed transition
   set — succinctly, no row ever exits ``succeeded`` or
   ``failed_permanent``.

Mocking surface
---------------

* ``httpx.AsyncClient.post`` is patched at the class level so the
  ``async with httpx.AsyncClient(...)`` context manager constructed
  inside :func:`_async_deliver_webhook` still functions; only the
  ``post`` instance method is replaced. The replacement returns a
  ``SimpleNamespace(status_code=...)`` matching the
  ``resp.status_code`` access in the worker; no other ``httpx``
  surface is touched.
* :data:`app.tasks.webhook_tasks.celery_app.send_task` is replaced
  per-step. For the ``enqueue_failure`` action the replacement
  raises a synthetic ``RuntimeError`` so the worker hits the
  except branch that terminates the row as ``failed_permanent`` and
  records ``retry_enqueue_failed:`` in ``last_error``.

Session management
------------------

Mirrors the ``p8_session_factory`` / ``p4_session_factory`` patterns
in the sibling webhook property tests: a function-scoped factory
bound to ``test_engine`` yields fresh autocommit-style sessions for
seed inserts and verification queries. The worker normally opens
its own session via :func:`app.database.async_session`, which is
backed by the module-level ``app.database.engine``. That engine
caches asyncpg prepared statements against the schema OIDs that
were live at first connect, and the function-scoped ``test_engine``
fixture drops and recreates the schema on every test, which can
leave the worker's pool with stale plans pointing at OIDs that no
longer exist. The symptom is the worker's ``db.get(...)``
returning ``None`` for a row the test just committed via the
parallel factory.

We side-step the issue by monkeypatching
:data:`app.tasks.webhook_tasks.async_session` (the symbol the
worker imported from ``app.database``) to the per-test session
factory bound to ``test_engine``. Seed, worker, and verification
queries then share one engine and one connection pool, so the
worker reads the rows the test wrote without any cross-pool
visibility concern.

# Feature: api-platform-export, Property 10: Webhook delivery state machine
# Validates: Requirements 4.4, 4.5, 4.6, 4.7, 4.8
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import List, Tuple

import httpx
import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings, strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.core.webhook_secret_crypto import encrypt_signing_secret
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_subscription import WebhookSubscription
from app.tasks import webhook_tasks


# ── Constants ─────────────────────────────────────────────────────────

#: Action labels generated by Hypothesis. Each label drives the
#: monkeypatched HTTP and broker layers to a specific outcome:
#:
#: * ``success`` — HTTP 200 from the receiver.
#: * ``transient_fail`` — HTTP 503 from the receiver.
#: * ``permanent_fail`` — HTTP 410 from the receiver.
#: * ``enqueue_failure`` — HTTP 503 *and* the next-retry enqueue
#:   raises, exercising Req 4.7.
#:
#: The implementation does not branch on whether the HTTP error is
#: "transient" or "permanent"; both go through the shared
#: retry-or-terminate path. The two labels are kept distinct so a
#: future implementation that introduces the distinction (e.g. fast
#: termination on 4xx) would surface here as a state-machine drift
#: rather than silently subsume both into one branch.
_ACTIONS: Tuple[str, ...] = (
    "success",
    "transient_fail",
    "permanent_fail",
    "enqueue_failure",
)

#: Maximum delivery attempts before terminal failure. Mirrors
#: ``len(settings.webhook_retry_schedule_seconds)`` (currently 5)
#: which is what the worker uses as ``max_attempts``. Hard-coded
#: here so a future schedule-length change forces the property
#: test author to revisit the reference machine.
_MAX_ATTEMPTS: int = 5

#: Allowed transitions on the persisted ``status`` column. Each tuple
#: is ``(prev_state, next_state)``. Anything outside this set is a
#: state-machine violation and fails the property test on the
#: transition assertion. The set encodes:
#:
#: * Idempotent terminal re-runs (succeeded → succeeded,
#:   failed_permanent → failed_permanent).
#: * The forward edges out of pending and retrying.
#: * No edge out of either terminal state into a non-terminal one.
_ALLOWED_TRANSITIONS: frozenset = frozenset(
    {
        ("pending", "succeeded"),
        ("pending", "retrying"),
        ("pending", "failed_permanent"),
        ("retrying", "succeeded"),
        ("retrying", "retrying"),
        ("retrying", "failed_permanent"),
        ("succeeded", "succeeded"),
        ("failed_permanent", "failed_permanent"),
    }
)


# ── Strategies ────────────────────────────────────────────────────────

#: Sequences of 1..7 actions. Above seven the per-example DB write
#: cost outweighs the extra coverage at the property's cardinality;
#: every reachable state is observable inside seven steps because
#: ``_MAX_ATTEMPTS`` is 5 and one ``success`` or ``enqueue_failure``
#: is always enough to drive the row terminal.
_ACTION_SEQUENCE: st.SearchStrategy[List[str]] = st.lists(
    st.sampled_from(_ACTIONS), min_size=1, max_size=7
)


# ── Reference state machine ───────────────────────────────────────────


def _reference_step(
    state: str, attempt_count: int, action: str
) -> Tuple[str, int]:
    """Compute the next (state, attempt_count) given the current pair.

    Mirrors the branches in
    :func:`app.tasks.webhook_tasks._async_deliver_webhook`:

    * On a terminal state, every action is a no-op (the worker's
      early-return guard at the top of the body).
    * On ``success``, the row terminates as ``succeeded``. The worker
      sets ``attempt_count`` to ``max(1, attempt_count)`` so a first-
      try success records "one attempt made", whereas success on a
      retry preserves the failure count that led up to it.
    * On any non-success outcome, ``attempt_count`` increments first;
      if the new value is at or above :data:`_MAX_ATTEMPTS` the row
      terminates as ``failed_permanent`` (Req 4.6).
    * On ``enqueue_failure`` with retries remaining, the row also
      terminates as ``failed_permanent`` (Req 4.7) — the broker
      failure escalates immediately rather than waiting for the
      retry budget to exhaust.
    * Otherwise the row transitions to ``retrying``.

    Args:
        state: The persisted ``status`` before this step.
        attempt_count: The persisted ``attempt_count`` before this
            step.
        action: One of the labels in :data:`_ACTIONS`.

    Returns:
        ``(next_state, next_attempt_count)``.
    """
    if state in ("succeeded", "failed_permanent"):
        return state, attempt_count

    if action == "success":
        # The worker preserves the failure count when success arrives
        # on a retry; on a first-try success it bumps 0 → 1.
        return "succeeded", attempt_count if attempt_count > 0 else 1

    new_count = attempt_count + 1
    if new_count >= _MAX_ATTEMPTS:
        return "failed_permanent", new_count
    if action == "enqueue_failure":
        return "failed_permanent", new_count
    return "retrying", new_count


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def p10_session_factory(test_engine) -> async_sessionmaker:
    """Build a session factory bound to the function-scoped test engine.

    Each call yields a fresh :class:`AsyncSession` with no outer
    ``session.begin()`` wrapper, so commits between phases (seed →
    drive worker → verify) succeed without invalidating later
    operations across Hypothesis examples (mirrors the
    ``p8_session_factory`` / ``p4_session_factory`` patterns).

    ``expire_on_commit=False`` matches the production session factory
    so attribute access on inserted rows after commit behaves the
    same way the worker does.
    """
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )


# ── Helpers ───────────────────────────────────────────────────────────


async def _seed_delivery(
    session_factory: async_sessionmaker,
) -> str:
    """Insert a fresh owner, subscription, and pending delivery row.

    Per-call uuid suffixes on the user's email and the delivery id
    keep two Hypothesis examples on the same engine from colliding
    on the unique-email constraint or sharing a delivery row. The
    survey/permission rows are intentionally omitted — the worker
    does not consult them; it reads the delivery and the
    subscription only.

    Args:
        session_factory: The per-test session factory.

    Returns:
        The new delivery row's id.
    """
    delivery_id = str(uuid.uuid4())
    async with session_factory() as session:
        owner = User(
            email=f"p10-statemachine-{uuid.uuid4().hex[:12]}@example.com",
            hashed_password=hash_password("Test1234!"),
            display_name="P10 Owner",
        )
        session.add(owner)
        await session.flush()

        subscription = WebhookSubscription(
            user_id=owner.id,
            survey_id=None,
            target_url="https://hooks.example.com/p10",
            event_types=["response.created"],
            signing_secret_ciphertext=encrypt_signing_secret(
                f"whsec_{uuid.uuid4().hex[:24]}"
            ),
            active=True,
        )
        session.add(subscription)
        await session.flush()

        delivery = WebhookDelivery(
            id=delivery_id,
            subscription_id=subscription.id,
            event_type="response.created",
            payload={"event": "p10-statemachine", "marker": uuid.uuid4().hex},
            status="pending",
            attempt_count=0,
        )
        session.add(delivery)
        await session.commit()

    return delivery_id


async def _read_delivery(
    session_factory: async_sessionmaker, delivery_id: str
) -> Tuple[str, int]:
    """Read the persisted ``(status, attempt_count)`` for a delivery row.

    Uses a fresh session so the read is not contaminated by any
    transaction the worker may have left open in error (the worker
    commits in every code path that mutates the row).

    Args:
        session_factory: The per-test session factory.
        delivery_id: The delivery row's primary key.

    Returns:
        ``(status, attempt_count)``.
    """
    async with session_factory() as session:
        row = await session.get(WebhookDelivery, delivery_id)
        assert row is not None, (
            f"delivery row {delivery_id} disappeared mid-test; the "
            "worker should never DELETE the row"
        )
        return row.status, row.attempt_count


def _install_action_mocks(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """Wire the HTTP and broker mocks for one worker invocation.

    Replaces :meth:`httpx.AsyncClient.post` at the class level with an
    async stub that returns a ``SimpleNamespace(status_code=...)``;
    the worker only reads ``status_code`` on the returned object so a
    namespace stub is sufficient. Replaces
    :data:`webhook_tasks.celery_app.send_task` with either a no-op
    stub or one that raises, depending on the action.

    Class-level patching of ``AsyncClient.post`` is preferred over
    patching the constructor because the worker uses ``async with
    httpx.AsyncClient(...) as client``: the context manager protocol
    must keep functioning, so leaving the rest of ``AsyncClient``
    intact is the lowest-blast-radius mock.

    Args:
        monkeypatch: The pytest monkeypatch fixture; patches are
            unwound at test teardown.
        action: One of the labels in :data:`_ACTIONS`.
    """
    if action == "success":
        status_code = 200
        enqueue_raises = False
    elif action == "transient_fail":
        status_code = 503
        enqueue_raises = False
    elif action == "permanent_fail":
        status_code = 410
        enqueue_raises = False
    elif action == "enqueue_failure":
        status_code = 503
        enqueue_raises = True
    else:  # pragma: no cover — strategy is sealed to _ACTIONS
        raise AssertionError(f"unexpected action: {action!r}")

    async def _fake_post(self, url, *, content=None, headers=None):
        """Minimal stub for ``httpx.AsyncClient.post``.

        Matches the keyword-only signature the worker calls with:
        ``client.post(sub.target_url, content=body_bytes,
        headers=headers)``. Returns an object whose ``status_code``
        is the only attribute the worker reads.
        """
        return SimpleNamespace(status_code=status_code)

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    if enqueue_raises:

        def _fake_send_task(*args, **kwargs):
            """Simulate a broker outage during retry enqueue.

            The exception type is irrelevant because the worker's
            ``except Exception`` backstop converts any broker error
            into a terminal ``failed_permanent`` transition with
            ``last_error`` prefixed by ``retry_enqueue_failed:``.
            """
            raise RuntimeError("simulated broker outage")

    else:

        def _fake_send_task(*args, **kwargs):
            """Pretend a successful broker enqueue.

            The real ``send_task`` returns an
            :class:`celery.result.AsyncResult`; the worker only needs
            it not to raise, so a minimal stub satisfies the contract.
            """
            return SimpleNamespace(id="fake-task-id")

    monkeypatch.setattr(webhook_tasks.celery_app, "send_task", _fake_send_task)


def _install_session_factory_override(
    monkeypatch: pytest.MonkeyPatch, factory: async_sessionmaker
) -> None:
    """Point the worker's ``async_session`` at the per-test factory.

    The worker module imported the symbol with
    ``from ..database import async_session``, so the binding lives on
    :mod:`app.tasks.webhook_tasks` rather than on
    :mod:`app.database`. We patch the worker-side reference so the
    ``async with async_session() as db`` block at the top of
    :func:`_async_deliver_webhook` uses the same engine the test seed
    and verification queries use. Without this redirection the
    worker's stock engine caches asyncpg prepared statements against
    the previous schema OIDs (the function-scoped ``test_engine``
    drops and recreates the schema for every test), which makes
    rows inserted on the test engine invisible to the worker pool.

    Args:
        monkeypatch: The pytest monkeypatch fixture; the patch is
            unwound at test teardown.
        factory: The per-test session factory bound to
            ``test_engine``.
    """
    monkeypatch.setattr(webhook_tasks, "async_session", factory)


# ── The property test ─────────────────────────────────────────────────


# Feature: api-platform-export, Property 10: Webhook delivery state machine
# Validates: Requirements 4.4, 4.5, 4.6, 4.7, 4.8
@pytest.mark.asyncio
@given(actions=_ACTION_SEQUENCE)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p10_webhook_delivery_state_machine(
    p10_session_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    actions: List[str],
) -> None:
    """Persisted (status, attempt_count) tracks the reference machine.

    Sub-invariants asserted at every step:

    * The persisted ``(status, attempt_count)`` after the worker
      returns equals the reference machine's prediction. A
      mismatch indicates the worker either skipped a state, took an
      illegal transition, or miscounted attempts.
    * The transition from the previous persisted ``status`` to the
      current persisted ``status`` is in
      :data:`_ALLOWED_TRANSITIONS`. This guards against the worker
      ever leaving a terminal state (the most common bug class for
      retry-driven state machines) and against any other illegal
      edge a future refactor might accidentally introduce.

    Validates: Requirements 4.4, 4.5, 4.6, 4.7, 4.8.
    """
    delivery_id = await _seed_delivery(p10_session_factory)
    _install_session_factory_override(monkeypatch, p10_session_factory)

    expected_state = "pending"
    expected_count = 0

    for step_idx, action in enumerate(actions):
        prev_state = expected_state
        expected_state, expected_count = _reference_step(
            expected_state, expected_count, action
        )

        _install_action_mocks(monkeypatch, action)
        await webhook_tasks._async_deliver_webhook(delivery_id)

        actual_state, actual_count = await _read_delivery(
            p10_session_factory, delivery_id
        )

        assert (actual_state, actual_count) == (expected_state, expected_count), (
            "state-machine drift at step "
            f"{step_idx} (action={action!r}): "
            f"expected=({expected_state!r}, {expected_count}), "
            f"actual=({actual_state!r}, {actual_count}). "
            f"actions={actions!r}"
        )

        assert (prev_state, actual_state) in _ALLOWED_TRANSITIONS, (
            "illegal state-machine transition at step "
            f"{step_idx} (action={action!r}): "
            f"{prev_state!r} → {actual_state!r}. "
            f"actions={actions!r}"
        )


# Feature: api-platform-export, Property 10: Webhook delivery state machine
# Validates: Requirements 4.4, 4.5, 4.6, 4.7, 4.8
def test_p10_max_attempts_matches_settings_schedule() -> None:
    """The reference machine's max_attempts equals the worker's.

    A regression that lengthens or shortens
    :attr:`Settings.webhook_retry_schedule_seconds` would silently
    desync the reference machine encoded in :func:`_reference_step`
    from the worker's actual behaviour. Pinning the relationship
    here surfaces the drift before the property test fires and lets
    a future schedule change be a one-line update with a clear
    failure mode.
    """
    from app.config import settings

    assert _MAX_ATTEMPTS == len(settings.webhook_retry_schedule_seconds), (
        f"_MAX_ATTEMPTS={_MAX_ATTEMPTS} but the worker uses "
        f"len(webhook_retry_schedule_seconds)="
        f"{len(settings.webhook_retry_schedule_seconds)}; update the "
        "constant and any reachable-states reasoning that depends on it"
    )

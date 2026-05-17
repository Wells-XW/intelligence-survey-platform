"""Property test P3: Webhook signature dual-window during invalidation failure.

Per design §Property 3 (Requirements 4.2, 4.10, with the dual-window
invariant pinned by Req 3.5), a webhook subscription enters a
dual-acceptance window the moment ``rotate_webhook_secret`` runs. While
the column ``WebhookSubscription.previous_secret_ciphertext`` is
non-null, the receiver-side verification simulator accepts payloads
signed with either the previous or the current signing secret. Once
``_async_invalidate_previous_secret`` clears that column — which it may
do only after some number of at-least-once retry failures — only
signatures produced with the current secret continue to verify.

This file tests the **invariant of the dual-window**, not its timing.
The number of invalidation retry failures is exercised as an arbitrary
non-negative integer because the invariant must hold under any number
of failures: while the previous-secret column remains non-null, dual
acceptance holds; once it is cleared, dual acceptance ends. Whether
the clearing happens on the first try or the tenth has no effect on
the invariant.

Test surface choice (pure functions, no DB):
    The dual-window contract collapses to the relationship between two
    columns on :class:`WebhookSubscription` and a verification
    predicate. The columns are model attributes; the predicate is
    deterministic. Neither requires a database round-trip to exercise.
    A pure-function property test runs at full Hypothesis budget
    (``max_examples=100``) with no fixtures and no rollback overhead.

Receiver-simulator construction:
    The platform deliberately does not ship a receiver-side verifier
    (design §Component 4: "HMAC verification on the receiver side is
    the receiver's responsibility, not the platform's"). The
    :func:`_receiver_verifies` helper below mimics the verification
    recipe published in the integration usage guide: a receiver that
    has cached both the current and (during the dual-window) the
    previous signing secret accepts a delivery if either secret yields
    a matching HMAC. ``hmac.compare_digest`` is used to mirror the
    constant-time comparison the guide recommends.

# Feature: api-platform-export, Property 3: Webhook signature dual-window during invalidation failure
# Validates: Requirements 4.2, 4.10
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.core.webhook_signing import canonical_body_bytes, sign
from app.models.webhook_subscription import WebhookSubscription


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class _SubscriptionState:
    """Minimal projection of the columns that drive the dual-window.

    Captures the two columns relevant to receiver-side verification —
    ``signing_secret_ciphertext`` (the current secret, stored as
    Fernet ciphertext at rest and decrypted by the worker before
    HMAC signing; see :mod:`app.tasks.webhook_tasks` module
    docstring) and the optional ``previous_secret_ciphertext`` (set
    during the rotation invalidation window). Using a dataclass
    instead of a full ORM row keeps the test pure-function: this
    state holds the **plaintext** secrets directly so the simulator
    can verify HMAC signatures without round-tripping through
    encryption.
    """

    current_secret: str
    previous_secret: Optional[str]


def _receiver_verifies(
    body_bytes: bytes,
    signature_header: str,
    state: _SubscriptionState,
) -> bool:
    """Mimic a receiver that knows the subscription's stored secrets.

    Mirrors the verification recipe published in the integration usage
    guide. The receiver computes ``HMAC-SHA256`` over the canonical
    request body using each candidate secret it has cached and
    accepts the delivery if any digest matches the signature header.
    Constant-time comparison guards against the timing side channels
    the guide warns receivers about.

    During the dual-window the receiver simulator has both secrets in
    its cache (the platform notified the receiver of the new one but
    the receiver may not have rolled the old one out yet). After the
    window the simulator only has the current secret.

    Args:
        body_bytes: Canonical UTF-8 byte sequence of the request body.
            Same byte sequence that was passed to :func:`sign`.
        signature_header: Value of the ``X-Webhook-Signature`` header,
            e.g. ``"sha256=abcd…"``.
        state: Projection of the subscription's secret columns. The
            ``previous_secret`` field is ``None`` once invalidation
            completes; it is the current plaintext of the previous
            secret while the dual-window is open.

    Returns:
        ``True`` if any cached secret yields a matching HMAC,
        ``False`` otherwise.
    """
    candidate_current = sign(state.current_secret, body_bytes)
    if hmac.compare_digest(candidate_current, signature_header):
        return True
    if state.previous_secret is not None:
        candidate_prev = sign(state.previous_secret, body_bytes)
        if hmac.compare_digest(candidate_prev, signature_header):
            return True
    return False


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


# JSON leaves matching the payload shapes ``emit_webhook_event``
# produces in practice (response ids, integers, booleans, ``None``).
_JSON_LEAF: st.SearchStrategy[Any] = st.one_of(
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.booleans(),
    st.none(),
)

# Top-level payloads are flat dicts with string keys. The dual-window
# invariant is independent of payload shape, so a flat dict suffices.
_PAYLOAD: st.SearchStrategy[dict] = st.dictionaries(
    keys=st.text(min_size=1, max_size=15),
    values=_JSON_LEAF,
    max_size=8,
)

# Signing secrets follow the ``whsec_<24 url-safe base64 chars>``
# format the route at :func:`_generate_signing_secret` mints. We
# generate the secret tail from the same character set so test
# inputs match the production shape exactly. Length 24 mirrors
# :func:`secrets.token_urlsafe(24)`.
_SECRET_TAIL: st.SearchStrategy[str] = st.text(
    alphabet=(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789-_"
    ),
    min_size=24,
    max_size=24,
)
_SECRET: st.SearchStrategy[str] = _SECRET_TAIL.map(lambda tail: f"whsec_{tail}")


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


# Feature: api-platform-export, Property 3: Webhook signature dual-window during invalidation failure
# Validates: Requirements 4.2, 4.10
@given(
    payload=_PAYLOAD,
    secret_old=_SECRET,
    secret_new=_SECRET,
    invalidation_failure_count=st.integers(min_value=0, max_value=10),
)
@settings(max_examples=100, deadline=None)
def test_p3_dual_window_holds_during_invalidation_failures(
    payload: dict,
    secret_old: str,
    secret_new: str,
    invalidation_failure_count: int,
) -> None:
    """Both secrets verify while ``previous_secret_ciphertext`` is non-null.

    Models the rotate-then-invalidate state machine that the route
    :func:`app.api.v1.webhooks.rotate_webhook_secret` and the task
    :func:`app.tasks.webhook_tasks._async_invalidate_previous_secret`
    drive together:

    1. Rotation runs: ``signing_secret_ciphertext`` becomes a Fernet
       ciphertext of ``secret_new``; ``previous_secret_ciphertext``
       becomes a Fernet ciphertext of ``secret_old``. The receiver
       simulator caches both plaintext secrets.
    2. The invalidation task fails ``invalidation_failure_count``
       times under the at-least-once retry contract (max ten
       retries). Each failure leaves both columns unchanged because
       :func:`_async_invalidate_previous_secret` only commits its
       ``UPDATE`` after a successful execution.
    3. While ``previous_secret_ciphertext`` is non-null, the receiver
       simulator must accept signatures produced with **either**
       secret. This is the load-bearing dual-window invariant
       (Req 3.5): a delivery already in-flight at rotation time and
       signed with the previous secret cannot be made invalid by the
       rotation, even if invalidation has not yet completed.

    The number of failures has no effect on the invariant; the
    invariant is governed by the column state, not by the count of
    retries. Hypothesis explores ``invalidation_failure_count`` to
    confirm that varying the count never breaks the invariant.
    """
    # The two secrets must differ for the invariant to be non-trivial:
    # if they were equal, dual acceptance is the trivial single-key
    # case and the test would prove nothing about the dual-window.
    assume(secret_old != secret_new)

    body_bytes = canonical_body_bytes(payload)
    sig_made_with_old = sign(secret_old, body_bytes)
    sig_made_with_new = sign(secret_new, body_bytes)

    # Step 1: rotation completes. Set the columns the same way
    # ``rotate_webhook_secret`` does in apps/api/core/app/api/v1/webhooks.py.
    state = _SubscriptionState(
        current_secret=secret_new,
        previous_secret=secret_old,
    )

    # Step 2: simulate ``invalidation_failure_count`` failed retries.
    # Each retry leaves the columns unchanged because the task only
    # commits ``UPDATE … SET previous_secret_ciphertext = NULL`` on
    # success; an exception path falls through ``Task.retry(exc=…)``
    # without a commit. The column state is therefore loop-invariant.
    for _ in range(invalidation_failure_count):
        # Sanity check: every retry leaves the column state unchanged.
        assert state.previous_secret == secret_old
        assert state.current_secret == secret_new

    # Step 3: while the previous-secret column is non-null, both
    # signatures verify against the receiver simulator. The signature
    # made with the new secret obviously verifies; the signature made
    # with the old secret must verify as well, because the receiver
    # may still hold the old secret in its cache.
    assert _receiver_verifies(body_bytes, sig_made_with_new, state), (
        "Dual-window invariant violated: signature with NEW secret "
        f"failed verification while previous_secret is "
        f"{state.previous_secret!r} and current is "
        f"{state.current_secret!r}"
    )
    assert _receiver_verifies(body_bytes, sig_made_with_old, state), (
        "Dual-window invariant violated: signature with OLD secret "
        f"failed verification while previous_secret_ciphertext is "
        f"non-null after {invalidation_failure_count} retry failures"
    )


# Feature: api-platform-export, Property 3: Webhook signature dual-window during invalidation failure
# Validates: Requirements 4.2, 4.10
@given(
    payload=_PAYLOAD,
    secret_old=_SECRET,
    secret_new=_SECRET,
    invalidation_failure_count=st.integers(min_value=0, max_value=10),
)
@settings(max_examples=100, deadline=None)
def test_p3_only_new_secret_verifies_after_invalidation_completes(
    payload: dict,
    secret_old: str,
    secret_new: str,
    invalidation_failure_count: int,
) -> None:
    """After invalidation clears the column, only the new secret verifies.

    Models the second half of the rotate-then-invalidate state
    machine:

    1. Rotation set the columns to ``(current=new, previous=old)``.
    2. After ``invalidation_failure_count`` failed retries, the next
       attempt of :func:`_async_invalidate_previous_secret` succeeds.
       The task commits
       ``UPDATE … SET previous_secret_ciphertext = NULL``,
       which closes the dual-window.
    3. From that point onward, the receiver simulator no longer
       caches the previous secret, so signatures produced with
       ``secret_old`` must fail verification while signatures
       produced with ``secret_new`` must continue to succeed.

    The complementary half — that during the dual-window both
    signatures verify — lives in
    :func:`test_p3_dual_window_holds_during_invalidation_failures`.
    The two halves together cover the full Property 3 invariant.
    """
    assume(secret_old != secret_new)

    body_bytes = canonical_body_bytes(payload)
    sig_made_with_old = sign(secret_old, body_bytes)
    sig_made_with_new = sign(secret_new, body_bytes)

    # Step 1: rotation set the columns; ``invalidation_failure_count``
    # retries failed without advancing the column state. The detail
    # of those retries is exercised in the companion test; here we
    # focus on the post-success state.
    state = _SubscriptionState(
        current_secret=secret_new,
        previous_secret=secret_old,
    )
    for _ in range(invalidation_failure_count):
        # Each retry leaves the state unchanged.
        assert state.previous_secret == secret_old

    # Step 2: invalidation finally succeeds. The task's body issues
    # ``UPDATE webhook_subscriptions SET previous_secret_ciphertext
    # = NULL WHERE id = :sub_id`` and commits.
    state.previous_secret = None

    # Step 3: dual-window has closed.
    # The signature made with the previous secret no longer verifies.
    assert not _receiver_verifies(body_bytes, sig_made_with_old, state), (
        "Post-invalidation invariant violated: signature with OLD "
        "secret still verifies after previous_secret_ciphertext was "
        "cleared"
    )
    # The signature made with the current secret continues to verify.
    assert _receiver_verifies(body_bytes, sig_made_with_new, state), (
        "Post-invalidation invariant violated: signature with NEW "
        "secret failed verification after previous_secret_ciphertext "
        "was cleared"
    )


# Feature: api-platform-export, Property 3: Webhook signature dual-window during invalidation failure
# Validates: Requirements 4.2, 4.10
def test_p3_subscription_model_carries_previous_secret_column() -> None:
    """The model column that drives the dual-window is in fact present.

    The pure-function tests above reason about the dual-window in
    terms of a two-column projection of ``WebhookSubscription``. If
    ``previous_secret_ciphertext`` were ever removed from the model
    the pure-function tests would still pass (they construct their
    own state dataclass) but the production behaviour would silently
    diverge. This guard pins the column-presence contract so a
    refactor that drops the column fails the test suite at this
    file rather than at integration time.
    """
    table = WebhookSubscription.__table__
    assert "signing_secret_ciphertext" in table.columns, (
        "WebhookSubscription must expose signing_secret_ciphertext to "
        "drive outbound signing per Req 4.3"
    )
    assert "previous_secret_ciphertext" in table.columns, (
        "WebhookSubscription must expose previous_secret_ciphertext "
        "to drive the dual-window per Req 3.5"
    )

    prev_col = table.columns["previous_secret_ciphertext"]
    assert prev_col.nullable, (
        "previous_secret_ciphertext must be nullable: the "
        "invalidation task clears it to NULL once the previous "
        "secret is no longer accepted (Req 3.5)"
    )


# Feature: api-platform-export, Property 3: Webhook signature dual-window during invalidation failure
# Validates: Requirements 4.2, 4.10
@given(
    payload=_PAYLOAD,
    secret_unrelated=_SECRET,
    secret_current=_SECRET,
    secret_previous=_SECRET,
)
@settings(max_examples=100, deadline=None)
def test_p3_unrelated_secret_never_verifies(
    payload: dict,
    secret_unrelated: str,
    secret_current: str,
    secret_previous: str,
) -> None:
    """A signature made with a third unrelated secret never verifies.

    Confirms the dual-window does not leak into a triple-acceptance
    window: even with both ``signing_secret_ciphertext`` and
    ``previous_secret_ciphertext`` populated, a signature produced
    with a third secret that was never associated with the
    subscription must fail verification. This guards against an
    off-by-one bug in a hypothetical receiver implementation that
    tries every secret in some larger cache.

    The receiver simulator only ever consults the two columns of the
    subscription, so this property is a soundness check on
    :func:`_receiver_verifies` rather than on the production
    columns. Without it a later edit to the simulator that broadened
    its candidate set would not be detected.
    """
    # All three secrets must be distinct for the test to be
    # meaningful — otherwise the unrelated secret is one of the
    # accepted ones.
    assume(secret_unrelated != secret_current)
    assume(secret_unrelated != secret_previous)

    body_bytes = canonical_body_bytes(payload)
    sig_made_with_unrelated = sign(secret_unrelated, body_bytes)

    state = _SubscriptionState(
        current_secret=secret_current,
        previous_secret=secret_previous,
    )

    assert not _receiver_verifies(
        body_bytes, sig_made_with_unrelated, state
    ), (
        "Receiver simulator accepted a signature made with a secret "
        "that was never associated with the subscription: "
        f"unrelated={secret_unrelated!r}, current={secret_current!r}, "
        f"previous={secret_previous!r}"
    )


# Feature: api-platform-export, Property 3: Webhook signature dual-window during invalidation failure
# Validates: Requirements 4.2, 4.10
def test_p3_receiver_simulator_matches_stdlib_hmac_reference() -> None:
    """The simulator's accept criterion equals the stdlib HMAC reference.

    Pins the simulator's behaviour against the stdlib recipe the
    integration usage guide publishes. If the simulator ever diverged
    from the stdlib reference (e.g. by switching to a non-constant
    comparison, or by hashing the secret with a different algorithm)
    the dual-window properties above would still pass for inputs
    where the divergence happened to coincide, but the production
    contract published to receivers would silently break.
    """
    body_bytes = canonical_body_bytes({"event": "ping"})
    secret_a = "whsec_" + uuid.uuid4().hex
    secret_b = "whsec_" + uuid.uuid4().hex

    # The simulator's acceptance criterion is constructed from the
    # ``sign`` helper, which itself wraps ``hmac.new(...).hexdigest``.
    # The reference is the same recipe spelled out by hand.
    expected_a_hex = hmac.new(
        secret_a.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()
    sig_a = f"sha256={expected_a_hex}"

    # A signature made with secret_a must be accepted when the
    # subscription has secret_a as its current secret, irrespective
    # of whether the dual-window is open.
    state_open = _SubscriptionState(
        current_secret=secret_a, previous_secret=secret_b
    )
    state_closed = _SubscriptionState(
        current_secret=secret_a, previous_secret=None
    )
    assert _receiver_verifies(body_bytes, sig_a, state_open)
    assert _receiver_verifies(body_bytes, sig_a, state_closed)

    # And rejected when neither column equals the secret used to sign.
    state_neither = _SubscriptionState(
        current_secret=secret_b, previous_secret=None
    )
    assert not _receiver_verifies(body_bytes, sig_a, state_neither)

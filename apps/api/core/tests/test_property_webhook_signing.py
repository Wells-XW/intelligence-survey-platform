"""Property-based tests for the webhook signing module.

This module validates Property 9 (Webhook request construction) from
``.kiro/specs/api-platform-export/design.md``:

    For any delivery with a unique delivery identifier, an event type,
    a body byte sequence, and a current signing secret, the constructed
    outbound HTTPS request carries ``Content-Type: application/json``,
    ``X-Webhook-Event`` equal to the event type, ``X-Webhook-Delivery``
    equal to the delivery identifier, and ``X-Webhook-Signature`` equal
    to ``sha256=<hex>`` where ``<hex>`` equals
    ``hmac.new(secret_bytes, body_bytes, sha256).hexdigest()`` from the
    standard library reference.

Validates: Requirements 4.2, 4.3.

The tests are deliberately pure: they do not touch the database, Redis,
or the FastAPI application. They exercise the four public functions in
``app.core.webhook_signing`` (``canonical_body_bytes``, ``sign``,
``build_delivery_headers``, ``USER_AGENT``) directly. This keeps the
property tests fast enough to run with ``max_examples=100`` and isolates
the cryptographic and serialization invariants from the rest of the
delivery pipeline.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.webhook_signing import (
    USER_AGENT,
    build_delivery_headers,
    canonical_body_bytes,
    sign,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# A simple JSON-serializable payload value. We keep the leaf set narrow on
# purpose: every value is something both ``json.dumps`` and ``json.loads``
# round-trip exactly, which is what the canonical body invariants require.
_JSON_LEAF: st.SearchStrategy[Any] = st.one_of(
    st.text(),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.booleans(),
    st.none(),
)

# Top-level payloads are dicts with string keys and JSON-leaf values, mirroring
# the shapes ``emit_webhook_event`` actually constructs (e.g.
# ``{"survey_id": ..., "response_id": ..., "submitted_at": ...}``).
_PAYLOAD: st.SearchStrategy[dict] = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=_JSON_LEAF,
    max_size=8,
)

# Event types follow the codebase convention ``<resource>.<verb>``, e.g.
# ``response.created`` or ``quota.reached``. The regex is intentionally narrow
# so generated values look like real event labels rather than arbitrary text.
_EVENT_TYPE: st.SearchStrategy[str] = st.from_regex(
    r"\A[a-z]{2,12}\.[a-z_]{2,20}\Z",
    fullmatch=True,
)

# Delivery IDs are UUID v4 strings on the wire (per
# ``X-Webhook-Delivery`` in the design); ``st.uuids`` plus ``str`` matches that.
_DELIVERY_ID: st.SearchStrategy[str] = st.uuids().map(str)


def _make_signature_header(seed: bytes) -> str:
    """Return a syntactically valid ``sha256=<hex>`` header value.

    Args:
        seed: An arbitrary byte sequence; only used to derive a stable
            hex digest for use as the header value.

    Returns:
        A string of the form ``"sha256=<64 lowercase hex chars>"`` that
        matches the format ``app.core.webhook_signing.sign`` produces.
    """
    return f"sha256={hashlib.sha256(seed).hexdigest()}"


_SIGNATURE_HEADER: st.SearchStrategy[str] = st.binary(min_size=1, max_size=32).map(
    _make_signature_header
)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

@given(payload=_PAYLOAD, secret=st.text(min_size=8, max_size=64))
@settings(max_examples=100, deadline=None)
def test_p9_signature_matches_stdlib_hmac_reference(
    payload: dict, secret: str
) -> None:
    # Feature: api-platform-export, Property 9: Webhook request construction
    """The signature equals the stdlib HMAC-SHA256 reference.

    Computes ``canonical_body_bytes(payload)`` and feeds the same byte
    sequence to both ``sign`` and the stdlib reference
    ``hmac.new(secret.encode("utf-8"), body_bytes, sha256).hexdigest()``.
    The result of ``sign`` must equal ``f"sha256={expected}"``. This is
    the load-bearing invariant of Req 4.3: the receiver verifies its
    HMAC using exactly this stdlib recipe.
    """
    body_bytes = canonical_body_bytes(payload)

    expected_hex = hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    expected_header = f"sha256={expected_hex}"

    assert sign(secret, body_bytes) == expected_header


@given(
    event_type=_EVENT_TYPE,
    delivery_id=_DELIVERY_ID,
    signature_header=_SIGNATURE_HEADER,
)
@settings(max_examples=100, deadline=None)
def test_p9_headers_contain_required_fields(
    event_type: str, delivery_id: str, signature_header: str
) -> None:
    # Feature: api-platform-export, Property 9: Webhook request construction
    """All five required webhook delivery headers are present and correct.

    Asserts the dict returned by ``build_delivery_headers`` carries the
    exact five-header surface required by Req 4.2: ``Content-Type`` is
    fixed at ``application/json``, ``User-Agent`` matches the module's
    ``USER_AGENT`` constant, and the three ``X-Webhook-*`` headers carry
    the values supplied by the caller verbatim.
    """
    headers = build_delivery_headers(event_type, delivery_id, signature_header)

    expected_keys = {
        "Content-Type",
        "User-Agent",
        "X-Webhook-Event",
        "X-Webhook-Delivery",
        "X-Webhook-Signature",
    }
    assert set(headers) == expected_keys

    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == USER_AGENT
    assert headers["X-Webhook-Event"] == event_type
    assert headers["X-Webhook-Delivery"] == delivery_id
    assert headers["X-Webhook-Signature"] == signature_header


@given(
    payload=st.dictionaries(
        keys=st.text(
            alphabet="一二三的为是中国人测试abc",
            min_size=1,
            max_size=10,
        ),
        values=st.one_of(
            st.text(alphabet="一二三的为是中国人测试abc", min_size=0, max_size=10),
            st.integers(min_value=-(2**31), max_value=2**31 - 1),
            st.booleans(),
            st.none(),
        ),
        max_size=6,
    ),
)
@settings(max_examples=100, deadline=None)
def test_p9_canonical_body_no_whitespace_no_ascii_escape(payload: dict) -> None:
    # Feature: api-platform-export, Property 9: Webhook request construction
    """Canonical body bytes contain no separator whitespace and round-trip.

    The canonical serialization in ``app.core.webhook_signing`` uses
    ``separators=(",", ":")`` and ``ensure_ascii=False``. This test
    asserts two consequences of that choice:

    1. The output bytes never contain the optional whitespace
       (``", "`` or ``": "``) that ``json.dumps`` would otherwise insert
       between separator tokens. Any extra whitespace would break
       receiver-side HMAC verification because the receiver re-serializes
       its own body for the comparison.
    2. The output bytes round-trip via ``bytes.decode("utf-8")`` plus
       ``json.loads`` to a payload structurally equal to the input. This
       holds even when keys and values contain non-ASCII characters such
       as Chinese question text, which is the realistic case for the
       Intelligence Survey Platform.
    """
    body_bytes = canonical_body_bytes(payload)

    # Whitespace-between-separators check. We look only at the bytes that
    # follow a comma or colon to avoid false positives from incidental
    # spaces inside string values. ``json.dumps`` with the canonical
    # separators never emits ``", "`` or ``": "`` as adjacent bytes.
    assert b", " not in body_bytes
    assert b": " not in body_bytes

    # Round-trip equality. Python dict ``==`` compares by key-value pairs
    # regardless of insertion order, so the round-trip is exact even if
    # ``json.loads`` happens to restore keys in a different sequence.
    decoded = json.loads(body_bytes.decode("utf-8"))
    assert decoded == payload

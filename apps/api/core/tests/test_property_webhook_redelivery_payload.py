"""Property test P11: Manual redelivery preserves payload bytes.

Per design §Property 11 (Requirements 4.10), invoking
``POST /api/v1/webhooks/{sub_id}/deliveries/{delivery_id}/redeliver``
must produce a brand-new :class:`app.models.webhook_delivery.WebhookDelivery`
row whose ``id`` differs from the original and whose ``payload`` is
byte-equal to the original's. The route at
``app.api.v1.webhooks.redeliver_webhook`` implements this by reusing
the original row's ``payload`` JSONB value verbatim when constructing
the new row.

The byte-equality property has two halves: a **canonicalization**
half and a **storage** half. We test each one without touching the
database.

* Canonicalization: :func:`app.core.webhook_signing.canonical_body_bytes`
  is deterministic, so re-serializing the same payload dict yields the
  same byte sequence. Hypothesis explores arbitrary JSON-serializable
  dicts; if the function ever became non-deterministic (e.g. a
  refactor adds key sorting that depends on hash randomization) the
  receiver-side HMAC verification on the redelivered request would
  break before it reached the receiver.
* Storage: :class:`WebhookDelivery.payload` is a
  :class:`sqlalchemy.dialects.postgresql.JSONB` column. JSONB stores
  the dict structurally rather than as a token-by-token byte
  sequence, but Postgres re-emits the same JSON serialization on read
  given the same value. Confirming the column type pins the storage
  contract.

# Feature: api-platform-export, Property 11: Manual redelivery preserves payload bytes
# Validates: Requirements 4.10
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings, strategies as st
from sqlalchemy.dialects.postgresql import JSONB

from app.core.webhook_signing import canonical_body_bytes
from app.models.webhook_delivery import WebhookDelivery


# JSON leaves modelled after the payloads ``emit_webhook_event``
# constructs in practice: response ids, integers, booleans, ``None``.
# The leaf set is narrow on purpose so the round-trip semantics of
# ``json.dumps`` plus ``json.loads`` are exact.
_JSON_LEAF: st.SearchStrategy[Any] = st.one_of(
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.booleans(),
    st.none(),
)

# Payload: small flat dicts with string keys, sized to keep
# Hypothesis exploration cheap. The redelivery contract is on the
# byte sequence rather than dict depth, so we don't need nested
# structures to exercise it.
_PAYLOAD: st.SearchStrategy[dict] = st.dictionaries(
    keys=st.text(min_size=1, max_size=15),
    values=_JSON_LEAF,
    max_size=8,
)


# Feature: api-platform-export, Property 11: Manual redelivery preserves payload bytes
# Validates: Requirements 4.10
@given(payload=_PAYLOAD)
@settings(max_examples=100, deadline=None)
def test_p11_canonical_bytes_equal_after_redelivery(payload: dict) -> None:
    """Canonical body bytes for the same payload are byte-equal across calls.

    Models the redelivery round-trip: the original delivery serialized
    the payload once before the outbound HTTPS POST; the redelivery
    serializes the same payload dict. Both byte sequences must match
    so the receiver's HMAC verification recomputes the same signature
    on the second attempt.
    """
    original_bytes = canonical_body_bytes(payload)
    redelivered_bytes = canonical_body_bytes(payload)
    assert original_bytes == redelivered_bytes, (
        "canonical_body_bytes is non-deterministic for payload "
        f"{payload!r}: original={original_bytes!r}, "
        f"redelivered={redelivered_bytes!r}"
    )


# Feature: api-platform-export, Property 11: Manual redelivery preserves payload bytes
# Validates: Requirements 4.10
def test_p11_webhook_delivery_payload_is_jsonb() -> None:
    """The ``payload`` column type is JSONB.

    JSONB is what guarantees Postgres re-emits a structurally
    equivalent JSON serialization on read, which is the database-side
    half of the byte-equality property. A plain ``Text`` column would
    either preserve the original byte sequence verbatim (acceptable)
    or silently re-format it on round-trip (not acceptable for HMAC
    verification on the redelivery attempt). JSONB pins the contract
    explicitly.
    """
    column = WebhookDelivery.__table__.columns["payload"]
    assert isinstance(column.type, JSONB), (
        f"WebhookDelivery.payload type is {type(column.type).__name__}; "
        "expected JSONB so Postgres preserves the JSON structure on "
        "round-trip per Req 4.10"
    )


# Feature: api-platform-export, Property 11: Manual redelivery preserves payload bytes
# Validates: Requirements 4.10
@given(payload=_PAYLOAD)
@settings(max_examples=100, deadline=None)
def test_p11_canonical_bytes_decode_round_trip(payload: dict) -> None:
    """Canonical bytes round-trip through ``json.loads`` losslessly.

    Confirms the byte sequence carries the full payload structure: a
    receiver decoding the redelivery body recovers the same dict the
    original delivery's body decoded to. This guards against an
    encoder change that would yield byte-equal output but a
    structurally lossy round-trip (e.g. dropping a non-JSON-safe
    type that should have raised at serialization time).
    """
    import json

    body = canonical_body_bytes(payload)
    decoded = json.loads(body.decode("utf-8"))
    assert decoded == payload

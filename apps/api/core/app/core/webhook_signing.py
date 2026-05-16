"""Pure helpers for signing outbound webhook deliveries.

This module is intentionally I/O-free: it neither touches the database, nor
the network, nor application settings. All three public functions are
deterministic given their inputs, which keeps them trivially unit- and
property-testable. The webhook delivery worker (``app/tasks/webhook_tasks.py``)
imports these helpers and supplies the signing secret loaded from the
subscription record at call time.

The signature scheme is HMAC-SHA256 over the canonical UTF-8 byte sequence
of the JSON body. HMAC-SHA256 is the de-facto standard for webhook signing
(used by GitHub, Stripe, Slack, and most major SaaS platforms): it is fast
enough to compute on every delivery, gives 128-bit security against forgery,
and matches what virtually every receiver-side library already knows how to
verify. See design.md §Component 4.

Crucially, the body is serialized exactly once via :func:`canonical_body_bytes`
and the same byte sequence is fed to both :func:`sign` and the HTTP POST. This
removes any whitespace or key-order ambiguity that would otherwise cause the
receiver's verification to fail. ``ensure_ascii=False`` keeps non-ASCII
characters (e.g. Chinese question text) as their UTF-8 byte representation
rather than ``\\uXXXX`` escapes, matching the size and content the receiver
actually parses; ``separators=(",", ":")`` collapses the optional whitespace
that ``json.dumps`` would otherwise insert between keys and values.

The signature header value follows the GitHub convention
``sha256=<64 lowercase hex chars>``, so receivers can split on ``=`` and
dispatch on the algorithm tag if they ever need to support multiple schemes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

# Single source of truth for the User-Agent string sent on every webhook
# delivery. The value is documented in the integration usage guide so
# receivers can allow-list it for IDS / WAF rules. Keep this in sync with
# Req 4 AC2 in requirements.md.
USER_AGENT: str = "IntelligenceSurveyPlatform-Webhook/1.0"


def canonical_body_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize a JSON-serializable payload to canonical UTF-8 bytes.

    The serialization uses ``ensure_ascii=False`` so non-ASCII characters
    are emitted as their UTF-8 byte representation rather than
    ``\\uXXXX`` escape sequences, and ``separators=(",", ":")`` so no
    optional whitespace is inserted between tokens. The result is the
    exact byte sequence that must be both signed and POSTed; signing one
    representation and sending another would cause the receiver's HMAC
    verification to fail.

    Args:
        payload: A JSON-serializable mapping. Keys are emitted in
            insertion order, matching :func:`json.dumps` defaults.

    Returns:
        The canonical UTF-8 encoded byte representation of ``payload``.

    Raises:
        TypeError: If ``payload`` contains values that are not JSON
            serializable (e.g. ``datetime``, ``set``). Callers are
            expected to convert such values upstream.
    """
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def sign(secret: str, body_bytes: bytes) -> str:
    """Compute the ``X-Webhook-Signature`` header value for a delivery.

    Computes ``HMAC-SHA256(secret, body_bytes)`` and formats the result
    in the GitHub-style ``sha256=<hex>`` envelope. The hex digest is
    lowercase and exactly 64 characters; receivers should compare it
    using a constant-time function on their side.

    Args:
        secret: The subscription's current signing secret. Encoded as
            UTF-8 before being passed to :func:`hmac.new`.
        body_bytes: The exact byte sequence of the request body, as
            produced by :func:`canonical_body_bytes`. Must be the same
            bytes sent in the HTTP POST body.

    Returns:
        The signature header value, formatted as
        ``sha256=<64 lowercase hex chars>``.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def build_delivery_headers(
    event_type: str,
    delivery_id: str,
    signature_header: str,
) -> dict[str, str]:
    """Build the full set of webhook delivery HTTP headers.

    The returned mapping covers every header required by Req 4 AC2:
    ``Content-Type``, ``User-Agent``, ``X-Webhook-Event``,
    ``X-Webhook-Delivery``, and ``X-Webhook-Signature``. Callers
    typically pass the result directly to ``httpx.post(headers=...)``.

    Args:
        event_type: The event type label, e.g. ``"response.created"``.
            Sent verbatim in the ``X-Webhook-Event`` header so receivers
            can route on it without parsing the body.
        delivery_id: A UUID v4 string uniquely identifying this delivery
            attempt. Sent in the ``X-Webhook-Delivery`` header so the
            receiver can dedupe across retries.
        signature_header: The value returned by :func:`sign`, e.g.
            ``"sha256=ab12...cd"``. Sent in the ``X-Webhook-Signature``
            header.

    Returns:
        A new ``dict`` containing all five required headers. The dict is
        not shared between calls, so callers may safely mutate it.
    """
    return {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Webhook-Event": event_type,
        "X-Webhook-Delivery": delivery_id,
        "X-Webhook-Signature": signature_header,
    }

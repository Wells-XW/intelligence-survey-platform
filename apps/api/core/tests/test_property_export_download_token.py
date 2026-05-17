"""Property-based tests for the export download token verifier.

Feature: api-platform-export, Property 15: Export download authorization (token path A)
Validates: Requirements 5.10, 5.11

Scope
-----
Property 15 (design.md §Property 15) defines three accepted auth paths
for ``GET /api/v1/exports/{job_id}/download``:

(a) a valid signed download token whose ``jti`` equals the job id,
    whose ``purpose`` equals ``export_download``, and whose ``exp`` is
    in the future;
(b) the caller is authenticated as the job owner via JWT;
(c) the caller is authenticated by an API key whose owner is the job
    owner and whose scope list contains ``export:read``.

Paths (b) and (c) require a live FastAPI app + database to exercise
end-to-end and are covered by integration tests elsewhere. This module
covers path (a) — the token verification predicate as a pure function
exposed by ``app.core.export_download_token``. The verifier returns the
``user_id`` (``sub`` claim) on success and ``None`` on every failure
mode (signature tamper, ``jti`` mismatch, expiry, wrong purpose,
malformed token).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jose import jwt

from app.config import settings as app_settings
from app.core.export_download_token import PURPOSE, issue, verify


# ---------------------------------------------------------------------------
# Strategies — UUID-shaped strings keep the tests aligned with how the
# real callers (route handlers) construct user_id and job_id values.
# ---------------------------------------------------------------------------


_UUID_STRATEGY = st.uuids().map(str)


# ---------------------------------------------------------------------------
# Property 15 — Issue/verify roundtrip
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(user_id=_UUID_STRATEGY, job_id=_UUID_STRATEGY)
def test_p15_issue_then_verify_roundtrip(user_id: str, job_id: str) -> None:
    """A freshly issued token verifies and returns the original ``user_id``."""
    token = issue(user_id=user_id, job_id=job_id)
    recovered = verify(token, job_id)
    assert recovered == user_id


# ---------------------------------------------------------------------------
# Property 15 — jti mismatch returns None
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    user_id=_UUID_STRATEGY,
    job_id_a=_UUID_STRATEGY,
    job_id_b=_UUID_STRATEGY,
)
def test_p15_verify_returns_none_on_jti_mismatch(
    user_id: str,
    job_id_a: str,
    job_id_b: str,
) -> None:
    """A token bound to ``job_id_a`` does not verify against any other job id."""
    # Skip the degenerate case where the two ids happen to match — that
    # is the roundtrip case, not the mismatch case.
    if job_id_a == job_id_b:
        return
    token = issue(user_id=user_id, job_id=job_id_a)
    assert verify(token, job_id_b) is None


# ---------------------------------------------------------------------------
# Property 15 — Signature tamper returns None
# ---------------------------------------------------------------------------


def test_p15_verify_returns_none_on_signature_tamper() -> None:
    """Mutating the signature segment makes the token unverifiable."""
    user_id = "user-12345"
    job_id = "job-67890"
    token = issue(user_id=user_id, job_id=job_id)

    # JWT format is header.payload.signature. Tamper with the signature
    # by flipping enough characters that any base64url padding-bit
    # leniency cannot make the result decode to the original byte
    # sequence. We invert the entire signature segment via character
    # rotation, which guarantees the decoded HMAC bytes differ.
    parts = token.split(".")
    assert len(parts) == 3
    sig = parts[2]

    def _flip(c: str) -> str:
        if c.isalpha():
            return c.swapcase()
        if c.isdigit():
            return str((int(c) + 5) % 10)
        if c == "-":
            return "_"
        if c == "_":
            return "-"
        return c

    tampered_sig = "".join(_flip(c) for c in sig)
    tampered = ".".join([parts[0], parts[1], tampered_sig])

    assert tampered != token
    assert verify(tampered, job_id) is None


def test_p15_verify_returns_none_on_payload_tamper() -> None:
    """Mutating the payload segment also breaks verification."""
    user_id = "user-12345"
    job_id = "job-67890"
    token = issue(user_id=user_id, job_id=job_id)

    parts = token.split(".")
    assert len(parts) == 3
    # Re-encode the payload to a deliberately different string with
    # the same length-class. The signature will no longer match.
    tampered_payload = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    tampered = ".".join([parts[0], tampered_payload, parts[2]])

    assert tampered != token
    assert verify(tampered, job_id) is None


def test_p15_verify_returns_none_on_malformed_token() -> None:
    """Inputs that are not even shaped like a JWT return None."""
    assert verify("not-a-jwt", "job-anything") is None
    assert verify("", "job-anything") is None
    assert verify("only.two", "job-anything") is None


# ---------------------------------------------------------------------------
# Property 15 — Expired token returns None
# ---------------------------------------------------------------------------


def test_p15_verify_returns_none_on_expired() -> None:
    """A token whose ``exp`` lies in the past returns None.

    Implemented by issuing with a 1-second TTL and sleeping past it,
    which keeps the test deterministic without requiring a freezegun
    or jose internals override.
    """
    user_id = "user-expired"
    job_id = "job-expired"
    token = issue(user_id=user_id, job_id=job_id, ttl_seconds=1)

    # Sanity check: the freshly issued token verifies.
    assert verify(token, job_id) == user_id

    # Wait until the token is unambiguously expired. jose uses a small
    # leeway by default; sleeping 2 seconds clears it.
    time.sleep(2)
    assert verify(token, job_id) is None


def test_p15_verify_returns_none_on_manually_expired_payload() -> None:
    """A token crafted with ``exp`` already in the past returns None.

    This is a deterministic alternative to the ``time.sleep`` based
    expiration test. We mint a token directly with ``jose.jwt.encode``
    using the same secret/algorithm but with an ``exp`` set 60 seconds
    in the past, then assert the verifier rejects it.
    """
    user_id = "user-manually-expired"
    job_id = "job-manually-expired"
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": job_id,
        "purpose": PURPOSE,
        "iat": now - timedelta(seconds=120),
        "exp": now - timedelta(seconds=60),
    }
    expired_token = jwt.encode(
        payload,
        app_settings.jwt_secret,
        algorithm=app_settings.jwt_algorithm,
    )
    assert verify(expired_token, job_id) is None


# ---------------------------------------------------------------------------
# Property 15 — Wrong purpose returns None
# ---------------------------------------------------------------------------


def test_p15_verify_returns_none_on_wrong_purpose() -> None:
    """A token with a non-export ``purpose`` is rejected even if otherwise valid."""
    user_id = "user-wrong-purpose"
    job_id = "job-wrong-purpose"
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": job_id,
        "purpose": "something_else",
        "iat": now,
        "exp": now + timedelta(seconds=900),
    }
    bad_token = jwt.encode(
        payload,
        app_settings.jwt_secret,
        algorithm=app_settings.jwt_algorithm,
    )
    assert verify(bad_token, job_id) is None


def test_p15_verify_returns_none_on_missing_purpose() -> None:
    """A token with no ``purpose`` claim at all is rejected."""
    user_id = "user-no-purpose"
    job_id = "job-no-purpose"
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": job_id,
        "iat": now,
        "exp": now + timedelta(seconds=900),
    }
    bad_token = jwt.encode(
        payload,
        app_settings.jwt_secret,
        algorithm=app_settings.jwt_algorithm,
    )
    assert verify(bad_token, job_id) is None


def test_p15_verify_returns_none_on_non_string_sub() -> None:
    """A token whose ``sub`` is not a string is rejected.

    The verifier is typed: when the ``sub`` claim is missing or not a
    string, it falls through to ``return None`` rather than returning a
    spurious value.
    """
    job_id = "job-no-sub"
    now = datetime.now(timezone.utc)
    payload = {
        # sub absent.
        "jti": job_id,
        "purpose": PURPOSE,
        "iat": now,
        "exp": now + timedelta(seconds=900),
    }
    bad_token = jwt.encode(
        payload,
        app_settings.jwt_secret,
        algorithm=app_settings.jwt_algorithm,
    )
    assert verify(bad_token, job_id) is None


# ---------------------------------------------------------------------------
# Property 15 — Wrong signing secret returns None
# ---------------------------------------------------------------------------


def test_p15_verify_returns_none_on_wrong_secret() -> None:
    """A token signed with a different secret is rejected."""
    user_id = "user-wrong-secret"
    job_id = "job-wrong-secret"
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": job_id,
        "purpose": PURPOSE,
        "iat": now,
        "exp": now + timedelta(seconds=900),
    }
    foreign_token = jwt.encode(
        payload,
        "an-entirely-different-secret-not-the-app-one",
        algorithm=app_settings.jwt_algorithm,
    )
    assert verify(foreign_token, job_id) is None


# Ensure pytest discovers the property tests as ordinary functions.
if __name__ == "__main__":
    pytest.main([__file__, "-v"])

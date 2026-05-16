"""Pure helpers for API key plaintext generation and hash verification.

This module is intentionally I/O-free: it neither touches the database nor
reads settings. All functions are deterministic given their inputs (modulo the
CSPRNG used by :func:`generate_plaintext`), which keeps them trivially unit-
and property-testable.

The plaintext format is ``sk_<env>_<24 url-safe base64 chars>`` where
``<env>`` is one of ``"live"`` or ``"test"``. The first 11 characters
(``sk_<env>_`` plus three body chars) form the ``key_prefix`` used for fast
lookup in ``api_keys.key_prefix``. The full plaintext is hashed with SHA-256
(64 lowercase hex chars) for storage in ``api_keys.key_hash``.

SHA-256 is deliberately chosen over bcrypt: API keys are high-entropy machine
credentials (~144 bits), not low-entropy user passwords, so the bcrypt work
factor would only add per-request latency without improving the brute-force
margin. See design.md §Component 2.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# Allowed values for the ``env`` segment of the plaintext.
_ALLOWED_ENVS: frozenset[str] = frozenset({"live", "test"})

# Length of the random url-safe base64 body. ``secrets.token_urlsafe(18)``
# encodes 18 random bytes as 24 base64url characters with no padding, since
# 18 is a multiple of 3.
_BODY_BYTES: int = 18
_BODY_CHARS: int = 24

# Number of characters in ``key_prefix``: ``sk_`` (3) + env (4) + ``_`` (1)
# + 3 body chars = 11. Both ``sk_live_`` and ``sk_test_`` have length 8, so
# 11 always covers the full env tag plus 3 body chars.
_KEY_PREFIX_LEN: int = 11


def generate_plaintext(env: str) -> tuple[str, str, str]:
    """Generate a fresh API key plaintext along with its prefix and hash.

    Args:
        env: Environment tag, must be ``"live"`` or ``"test"``.

    Returns:
        A ``(plaintext, key_prefix, sha256_hex)`` triple where ``plaintext``
        is ``sk_<env>_<24 url-safe base64 chars>``, ``key_prefix`` is the
        first 11 characters of ``plaintext``, and ``sha256_hex`` is the
        lowercase 64-character hex digest of ``plaintext`` encoded as UTF-8.

    Raises:
        ValueError: If ``env`` is not one of ``"live"`` or ``"test"``.
    """
    if env not in _ALLOWED_ENVS:
        raise ValueError(
            f"env must be one of {sorted(_ALLOWED_ENVS)}, got {env!r}"
        )

    body = secrets.token_urlsafe(_BODY_BYTES)
    # ``token_urlsafe(18)`` returns exactly 24 chars; defensively assert the
    # invariant so a stdlib change cannot silently shift the prefix layout.
    assert len(body) == _BODY_CHARS, (
        f"expected token_urlsafe({_BODY_BYTES}) to return {_BODY_CHARS} chars, "
        f"got {len(body)}"
    )

    plaintext = f"sk_{env}_{body}"
    key_prefix = plaintext[:_KEY_PREFIX_LEN]
    sha256_hex = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return plaintext, key_prefix, sha256_hex


def verify(plaintext: str, expected_hash: str) -> bool:
    """Verify an API key plaintext against an expected SHA-256 hex digest.

    The comparison uses :func:`hmac.compare_digest` for constant-time
    behaviour, which avoids leaking match length via timing side channels.

    Args:
        plaintext: The candidate plaintext supplied by the caller.
        expected_hash: The lowercase 64-character SHA-256 hex digest stored
            alongside the API key record.

    Returns:
        ``True`` when the SHA-256 of ``plaintext`` (UTF-8 encoded) matches
        ``expected_hash``, ``False`` otherwise. Returns ``False`` rather
        than raising on type or length mismatches that would otherwise make
        the comparison undefined.
    """
    if not isinstance(plaintext, str) or not isinstance(expected_hash, str):
        return False
    actual_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual_hash, expected_hash)

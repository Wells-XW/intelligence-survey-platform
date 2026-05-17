"""Pure helpers for webhook signing-secret encryption at rest.

Background and rationale
------------------------

The original T15 implementation stored the plaintext webhook signing
secret in ``webhook_subscriptions.signing_secret_hash`` because the
delivery worker needs the plaintext to compute
``HMAC-SHA256(secret, body)``: SHA-256 is one-way, so a hash-only
column would have made outbound HMAC signing impossible. That choice
violated Property 1 (plaintext credential exposure is exactly-once)
because direct ``SELECT`` on the column surfaced the plaintext.

The post-T15 fix resolves the conflict between Req 3 AC3
("salted hash") and Req 4 AC3 ("HMAC-SHA256 keyed by the current
signing secret over the request body bytes") by storing a Fernet
ciphertext at rest. Fernet (a symmetric AEAD construction over
AES-128-CBC + HMAC-SHA-256) is reversible, so the worker can
decrypt the ciphertext on demand to sign outbound deliveries; the
``webhook_subscriptions.signing_secret_ciphertext`` column never
holds the plaintext bytes that satisfy the substring scans Property
1 performs against every persistence surface.

Module contract
---------------

This module is intentionally I/O-free. The two public functions
:func:`encrypt_signing_secret` and :func:`decrypt_signing_secret`
take and return strings, do not touch the database, and do not
import settings at module import time. They read
:attr:`Settings.webhook_secret_encryption_key` at call time so test
overrides via ``monkeypatch.setattr(settings, ...)`` take effect
without needing module-level reload.

Failure modes
-------------

The ``cryptography`` library raises
:class:`cryptography.fernet.InvalidToken` on malformed ciphertexts
and :class:`ValueError` (wrapped) on malformed keys; both are
re-raised verbatim. Callers should treat decryption failure as a
fatal data-integrity event rather than retrying — a corrupted
ciphertext means the subscription's signing secret has been lost.
"""

from __future__ import annotations

from cryptography.fernet import Fernet


def _build_fernet() -> Fernet:
    """Return a :class:`Fernet` instance bound to the current settings key.

    Reads ``settings.webhook_secret_encryption_key`` at call time so
    tests can override the key with
    ``monkeypatch.setattr(settings, "webhook_secret_encryption_key", ...)``
    after this module has been imported. The value must be a base64
    url-safe encoding of 32 raw bytes — the format produced by
    :meth:`Fernet.generate_key`. Any other value raises
    :class:`ValueError` from inside the ``cryptography`` library.

    Returns:
        A Fernet instance ready to encrypt or decrypt webhook signing
        secrets.

    Raises:
        ValueError: When the configured key is not a valid 32-byte
            url-safe base64 Fernet key.
    """
    # Local import keeps the module top-level free of side effects so
    # tests can monkeypatch the settings module before the first call.
    from ..config import settings

    key = settings.webhook_secret_encryption_key
    if isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def encrypt_signing_secret(plaintext: str) -> str:
    """Encrypt a webhook signing secret for at-rest storage.

    Wraps :meth:`Fernet.encrypt`. The Fernet token format embeds a
    version byte, a fresh 128-bit IV, the AES-128-CBC ciphertext, and
    an HMAC-SHA-256 tag, all base64 url-safe encoded. Each call
    produces a distinct ciphertext for the same plaintext because the
    IV is freshly randomized inside :meth:`Fernet.encrypt`.

    Args:
        plaintext: The webhook signing secret in the form
            ``whsec_<24 url-safe base64 chars>`` (the format minted by
            :func:`app.api.v1.webhooks._generate_signing_secret`).
            Empty strings are accepted and round-trip cleanly; the
            caller is responsible for validating non-emptiness at
            schema time.

    Returns:
        A base64 url-safe ASCII string containing the Fernet token.
        Suitable for storage in a ``VARCHAR``/``TEXT`` column without
        further encoding.

    Raises:
        ValueError: When the configured encryption key is not a valid
            Fernet key.
        TypeError: When ``plaintext`` is not a :class:`str`.
    """
    if not isinstance(plaintext, str):
        raise TypeError(
            f"plaintext must be str, got {type(plaintext).__name__}"
        )
    fernet = _build_fernet()
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_signing_secret(ciphertext: str) -> str:
    """Decrypt a Fernet-wrapped webhook signing secret.

    Wraps :meth:`Fernet.decrypt`. The integrity tag embedded in the
    Fernet token is verified before the plaintext is returned, so a
    tampered or truncated ciphertext raises
    :class:`cryptography.fernet.InvalidToken` rather than yielding
    garbage. There is no built-in TTL on Fernet tokens; the caller
    does not pass ``ttl`` because webhook signing secrets only become
    invalid through explicit rotation, not through token aging.

    Args:
        ciphertext: A Fernet token string produced by
            :func:`encrypt_signing_secret` or by an earlier deployment
            using the same key.

    Returns:
        The original plaintext signing secret.

    Raises:
        cryptography.fernet.InvalidToken: When the ciphertext fails
            integrity verification (corrupted, tampered, or encrypted
            with a different key).
        ValueError: When the configured encryption key is not a valid
            Fernet key.
        TypeError: When ``ciphertext`` is not a :class:`str`.
    """
    if not isinstance(ciphertext, str):
        raise TypeError(
            f"ciphertext must be str, got {type(ciphertext).__name__}"
        )
    fernet = _build_fernet()
    return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")

"""Signed download token helpers for the export pipeline.

Pure functions: no DB, no settings reads (settings is read once via
the existing config import). Used by the export route layer to mint
short-lived URLs that let non-API-aware tools (browsers, email
clients) fetch a rendered export without needing the user's JWT or
API key.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from ..config import settings

# Token purpose namespace. A leaked download token cannot be replayed
# against any other endpoint because the verifier checks this claim
# before honoring the rest of the payload.
PURPOSE: str = "export_download"


def issue(user_id: str, job_id: str, ttl_seconds: Optional[int] = None) -> str:
    """Mint a fresh download token for one export job.

    Args:
        user_id: The owning user's id; placed in ``sub``.
        job_id: The export job id; placed in ``jti``.
        ttl_seconds: Validity window in seconds. Defaults to
            ``settings.export_download_token_ttl_seconds`` (15 min).

    Returns:
        Encoded JWT (HS256, signed with ``settings.jwt_secret``).
    """
    ttl = ttl_seconds if ttl_seconds is not None else settings.export_download_token_ttl_seconds
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": job_id,
        "purpose": PURPOSE,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify(token: str, job_id: str) -> Optional[str]:
    """Verify a download token against an expected job id.

    Args:
        token: The encoded JWT presented by the caller.
        job_id: The expected job id from the URL path.

    Returns:
        The ``user_id`` (``sub`` claim) when valid; ``None`` when invalid
        for any reason — wrong purpose, ``jti`` mismatch, signature
        failure, expired, or malformed.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": True},
        )
    except JWTError:
        return None

    if payload.get("purpose") != PURPOSE:
        return None
    if payload.get("jti") != job_id:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str):
        return None
    return sub

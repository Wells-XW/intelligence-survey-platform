"""JWT token creation / verification and password hashing utilities."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext

from ..config import settings

# bcrypt password hashing
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str) -> str:
    """Create a short-lived JWT access token (default 15 minutes).

    Args:
        user_id: The user's UUID string.

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived JWT refresh token (default 7 days).

    Each token has a unique ``jti`` claim so it can be identified
    and revoked individually.

    Args:
        user_id: The user's UUID string.

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_refresh_token_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token.

    Args:
        token: The encoded JWT string.

    Returns:
        Decoded payload dictionary containing at least ``sub`` and ``type``.

    Raises:
        JWTError: If the token is invalid, expired, or tampered with.
    """
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"verify_exp": True},
    )


def hash_token(token: str) -> str:
    """SHA-256 hash a token string for database storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def validate_password(password: str) -> tuple[bool, str | None]:
    """Validate password strength.

    Requirements:
    - Minimum 8 characters
    - At least 1 letter
    - At least 1 digit

    Args:
        password: The plain-text password to validate.

    Returns:
        A tuple of (is_valid, error_message). error_message is None when valid.
    """
    if len(password) < 8:
        return False, "密码长度至少 8 个字符"
    if not any(c.isalpha() for c in password):
        return False, "密码必须包含至少一个字母"
    if not any(c.isdigit() for c in password):
        return False, "密码必须包含至少一个数字"
    return True, None

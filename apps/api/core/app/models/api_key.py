"""ApiKey ORM model — long-lived secret credentials for machine integrators."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class ApiKey(Base):
    """Server-issued API key bound to a single platform user.

    The key represents one of three lifecycle states, derived from the
    timestamp columns rather than a stored enum so the audit trail stays
    aligned with point-in-time queries:

    * Active — ``revoked_at IS NULL`` and (``expires_at IS NULL`` or
      ``expires_at > now()``). The key is accepted by the auth resolver
      and counts against its owner's rate-limit quotas.
    * Revoked — ``revoked_at IS NOT NULL``. Set when the owner self-revokes
      via the API or when an administrator forces revocation. Once set
      the key is permanently inert; rotation issues a fresh row instead
      of clearing this field.
    * Expired — ``expires_at`` is non-null and in the past. The key was
      issued with a bounded lifetime and has aged out without being
      explicitly revoked. Rejection happens at auth time only; the row
      is not retroactively rewritten when the deadline passes.

    Plaintext-shown-once contract:
        The full secret in the form ``sk_<env>_<24 url-safe chars>`` is
        returned to the caller exactly once at create or rotate time and
        is never persisted. Only ``key_prefix`` (the first 11 characters,
        e.g. ``sk_live_ab``) and ``key_hash`` (SHA-256 hex of the full
        plaintext) are stored. The prefix is uniquely indexed to keep
        per-request authentication lookups O(1); the hash is used to
        verify the presented secret on each call.

    Attributes:
        id: Primary key, UUID stored as a string.
        user_id: Foreign key to ``users.id`` with ``ON DELETE CASCADE``.
        name: Human-readable label set by the owner at creation time.
        key_prefix: First 11 characters of the plaintext secret;
            uniquely indexed for fast lookup by the auth resolver.
        key_hash: SHA-256 hex digest of the full plaintext secret.
        scopes: JSON array of scope strings drawn from the fixed enum
            defined in ``app/api/v1/api_keys.py``.
        rate_limit_overrides: Optional partial override map with keys
            among ``{"minute", "hour", "day"}``; missing windows fall
            back to platform defaults.
        expires_at: Optional bounded expiration; ``None`` means no
            time-based expiry.
        last_used_at: Best-effort timestamp updated on each successful
            authenticated request; used to compute the "inactive"
            display flag in list responses.
        revoked_at: Soft-delete marker; non-null indicates the key is
            permanently disabled.
        created_at: Insert timestamp.
        updated_at: Last-update timestamp; refreshed by the ORM on any
            mutation (rotation, revocation, override change).
        user: SQLAlchemy relationship to the owning :class:`User`.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(
        String(11), unique=True, nullable=False, index=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    rate_limit_overrides: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user = relationship("User", back_populates="api_keys")

    def __repr__(self) -> str:
        return (
            f"<ApiKey(id={self.id}, prefix={self.key_prefix!r}, "
            f"user_id={self.user_id})>"
        )

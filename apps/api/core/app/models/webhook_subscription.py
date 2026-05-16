"""WebhookSubscription ORM model — outbound HTTPS subscription for domain events."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class WebhookSubscription(Base):
    """Owner-scoped registration that forwards domain events to an external URL.

    Each row represents one ``(owner, target URL, event set)`` triple. The
    subscribed event types are validated app-side against the fixed enum
    ``{response.created, response.completed, quota.reached, distribution.sent}``
    before insert; a JSONB array is used so the set can grow without a
    schema migration. The optional ``survey_id`` scopes the subscription to
    a single survey; when ``None`` the subscription matches every survey
    the owner has at least viewer permission on.

    Signing-secret rotation contract:
        The plaintext signing secret is shown to the caller exactly once
        at create or rotate time and never persisted. Only the SHA-256
        hex digest of the current secret is stored in
        ``signing_secret_hash``. During the rotation invalidation window
        described in Req 3 AC5 the previous secret's hash is held in
        ``previous_secret_hash`` so receivers that have not yet picked up
        the new secret can still verify in-flight deliveries; the column
        is cleared by the invalidation Celery task once the previous
        secret is no longer accepted. Server-side outbound signing
        always uses the latest secret, never the previous one.

    Activation and last-delivery cache:
        ``active`` is the on/off toggle exposed via ``PATCH``;
        delivery enqueueing reads it on every fan-out and skips inactive
        rows without writing a delivery record. ``last_delivery_at`` and
        ``last_delivery_status`` are a denormalized cache of the most
        recent terminal delivery so the list-subscriptions endpoint can
        render health without joining ``webhook_deliveries``. Both
        columns are written by the delivery worker on terminal
        transition (``succeeded`` or ``failed_permanent``) and are
        intentionally eventually consistent with the delivery rows.

    Attributes:
        id: Primary key, UUID stored as a string.
        user_id: Foreign key to ``users.id`` with ``ON DELETE CASCADE``.
        survey_id: Optional foreign key to ``surveys.id`` with
            ``ON DELETE CASCADE``; ``None`` matches every survey the
            owner can see.
        target_url: Destination HTTPS URL; HTTPS-only validation runs
            app-side at create and update time.
        event_types: JSON array of event-type strings drawn from the
            fixed enum.
        description: Optional human-readable label.
        signing_secret_hash: SHA-256 hex of the current signing secret.
        previous_secret_hash: SHA-256 hex of the previous signing secret;
            non-null only during the rotation invalidation window.
        active: On/off toggle for delivery dispatch; defaults to True.
        last_delivery_at: Cached timestamp of the most recent terminal
            delivery; updated by the worker.
        last_delivery_status: Cached status of the most recent terminal
            delivery (``succeeded`` or ``failed_permanent``).
        created_at: Insert timestamp.
        updated_at: Last-update timestamp; refreshed by the ORM on any
            mutation.
        user: SQLAlchemy relationship to the owning :class:`User`.
        deliveries: Relationship to :class:`WebhookDelivery` rows. Cascade
            ``all, delete-orphan`` mirrors the FK ``ON DELETE CASCADE``
            so deleting a subscription removes its delivery history at
            both the ORM and the database level.
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    survey_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    event_types: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    signing_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_secret_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_delivery_status: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
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
    user = relationship("User")
    deliveries = relationship(
        "WebhookDelivery",
        back_populates="subscription",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<WebhookSubscription(id={self.id}, user_id={self.user_id}, "
            f"active={self.active})>"
        )

"""WebhookDelivery ORM model — single delivery attempt sequence for a webhook event."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class WebhookDelivery(Base):
    """Single delivery attempt sequence for one webhook event.

    A delivery row is inserted in status ``pending`` at the moment a
    domain event fan-out determines that a subscription should receive
    the event. The same row is reused across all retry attempts for
    that event; the worker increments ``attempt_count`` on the row
    rather than relying on Celery's ``self.request.retries`` so that a
    worker restart mid-flight cannot lose retry state. The row's
    ``id`` doubles as the value of the outbound ``X-Webhook-Delivery``
    HTTP header so receivers can dedupe duplicate retries that arrive
    after they had already accepted but failed to ACK in time.

    State machine:
        ``pending`` → ``succeeded``: HTTP 2xx received within the 10s
        timeout on any attempt. Terminal.

        ``pending`` → ``retrying``: network error, timeout, or non-2xx
        response on attempt 1, with attempts remaining. The worker
        increments ``attempt_count``, sets ``next_attempt_at`` to
        ``now + backoff(attempt_count)`` where the backoff schedule is
        ``{60s, 300s, 1800s, 7200s, 43200s}``, and re-enqueues itself
        with ``countdown``.

        ``retrying`` → ``retrying``: same as above on a subsequent
        attempt while attempts remain.

        ``retrying`` → ``succeeded``: HTTP 2xx on a retry attempt.
        Terminal.

        ``retrying`` → ``failed_permanent``: the fifth attempt
        (``attempt_count == 5``) failed, or the retry enqueue itself
        failed. Terminal.

    The state field is a plain ``VARCHAR(20)`` rather than a Postgres
    enum because the state set is expected to evolve (e.g. a future
    ``cancelled`` for manual termination) and Postgres enum migrations
    are heavyweight. Validation is enforced in the service layer.

    Attributes:
        id: Primary key, UUID stored as a string. Also sent as
            ``X-Webhook-Delivery`` to the receiver for dedupe.
        subscription_id: Foreign key to ``webhook_subscriptions.id``
            with ``ON DELETE CASCADE``.
        event_type: The event-type string at the time of fan-out, e.g.
            ``response.created``.
        payload: JSON body sent to the receiver. Preserved byte-for-byte
            so that manual redelivery (Req 4 AC10) reproduces the
            original signature input.
        status: Current state, one of ``pending`` / ``retrying`` /
            ``succeeded`` / ``failed_permanent``. Defaults to
            ``pending``.
        attempt_count: Number of HTTP attempts made; starts at 0 and is
            incremented before each outbound call.
        last_attempt_at: Timestamp of the most recent attempt; null
            until the first attempt completes.
        last_response_status: HTTP status code from the most recent
            attempt; null on network error or before the first attempt.
        last_error: Truncated (1000 chars) error message from the most
            recent failed attempt; null on success.
        next_attempt_at: Scheduled time of the next retry; non-null only
            while ``status == 'retrying'``.
        created_at: Insert timestamp; the moment fan-out decided to
            deliver this event.
        completed_at: Timestamp of terminal transition (success or
            permanent failure); null while non-terminal.
        subscription: SQLAlchemy relationship back to the owning
            :class:`WebhookSubscription`.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    subscription_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    subscription = relationship("WebhookSubscription", back_populates="deliveries")

    def __repr__(self) -> str:
        return (
            f"<WebhookDelivery(id={self.id}, "
            f"subscription_id={self.subscription_id}, "
            f"status={self.status!r}, attempt={self.attempt_count})>"
        )

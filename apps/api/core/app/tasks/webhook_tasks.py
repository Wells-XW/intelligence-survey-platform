"""Webhook delivery worker — outbound HTTPS POST with retry and reconciliation.

This module implements Component 5 of the API Open Platform design: the
single Celery task ``deliver_webhook`` that consumes the ``webhooks`` queue
plus a beat-driven reconciler that re-enqueues stuck ``pending`` deliveries.

Worker concurrency hints (set via the worker CLI, not on the app object)::

    celery -A app.tasks worker --queues=webhooks \\
        --concurrency=8 --prefetch-multiplier=4

Webhook delivery is I/O bound (HTTPS POST with a 10 s timeout). A higher
prefetch multiplier keeps a single slow target URL from stalling sibling
deliveries running on the same worker. This is intentionally different from
the AI generation worker, which uses ``prefetch_multiplier=1`` because LLM
calls are heavy and CPU-bound on the client side.

Retry semantics:
    The retry counter is the row's ``WebhookDelivery.attempt_count`` rather
    than ``self.request.retries`` from Celery so a worker restart mid-flight
    cannot lose state. After an attempt fails the worker increments
    ``attempt_count`` and indexes
    :attr:`Settings.webhook_retry_schedule_seconds` (the tuple
    ``(60, 300, 1800, 7200, 43200)``) by ``attempt_count - 1``. The fifth
    failed attempt drives the row into the terminal ``failed_permanent``
    state regardless of the schedule's remaining entries. If the retry
    enqueue itself raises, the row is marked ``failed_permanent`` immediately
    (Req 4.7).

Plaintext signing-secret column:
    The schema column ``WebhookSubscription.signing_secret_hash`` was named
    during an early design draft when we expected to verify a credential
    presented by the receiver. That pattern does not apply to outbound
    HMAC signing: the worker must hold the plaintext secret to compute
    ``HMAC-SHA256(secret, body)``, since SHA-256 is one-way. The column
    therefore stores the plaintext value directly; the ``_hash`` suffix is
    a misnomer that survives only because renaming the column would force
    another Alembic migration (deferred). Treat reads from
    ``signing_secret_hash`` as plaintext throughout this module.

Idempotency:
    The receiver gets the delivery's UUID in ``X-Webhook-Delivery``. It is
    the receiver's responsibility to dedupe by this id if a retry arrives
    after the receiver had already accepted a previous attempt but failed
    to ACK in time. The platform makes no exactly-once guarantee.

Audit emission:
    Both terminal states (``succeeded`` / ``failed_permanent``) emit exactly
    one audit row whose ``action`` is either ``webhook.delivery.succeeded``
    or ``webhook.delivery.failed`` and whose ``user_id`` is the subscription
    owner. The ``details`` JSONB carries ``subscription_id``, ``event_type``,
    ``attempt_count``, ``last_response_status``, and ``last_error`` so a
    compliance reviewer can reconstruct the delivery sequence without
    joining ``webhook_deliveries``.

Beat reconciler (operator hook):
    :func:`reconcile_pending_deliveries` scans for ``pending`` rows older
    than 60 seconds and re-enqueues them. It is intended to run on Celery
    beat every five minutes. The wiring lives in operations / deployment
    config and is intentionally not added here (out of scope for this task).
    Recommended schedule for ``celery beat``::

        beat_schedule = {
            "webhooks-reconcile-pending": {
                "task": "app.tasks.webhook_tasks.reconcile_pending_deliveries",
                "schedule": 300.0,  # 5 minutes
                "options": {"queue": "webhooks"},
            },
        }
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx
from sqlalchemy import select

from . import celery_app
from ..config import settings
from ..core.audit import log_audit
from ..core.webhook_signing import (
    build_delivery_headers,
    canonical_body_bytes,
    sign,
)
from ..database import async_session

logger = logging.getLogger(__name__)


# ── Module constants ──────────────────────────────────────────────────

#: Maximum length stored in ``WebhookDelivery.last_error``. Receivers'
#: error pages can be large; we keep the head of the message because the
#: HTTP status code carries the rest of the diagnostic value.
_LAST_ERROR_MAX_CHARS: int = 1000

#: Threshold for the reconciler. Rows in ``pending`` older than this are
#: assumed to have lost their Celery enqueue (e.g., a broker outage at
#: dispatch time on the API side) and are re-enqueued by the beat job.
_RECONCILE_PENDING_AGE_SECONDS: int = 60

#: Grace window before the previous signing secret is invalidated. The
#: rotate-secret route schedules :func:`invalidate_previous_secret` with
#: this countdown so receivers have time to pick up the new secret
#: without dropping in-flight deliveries signed with the old one. The
#: 24-hour default matches GitHub / Stripe rotation conventions and is
#: read both by the rotate-secret route (to schedule the task) and by
#: this task module (so callers can import a single canonical value).
PREVIOUS_SECRET_GRACE_SECONDS: int = 24 * 60 * 60


# ── Public Celery tasks ───────────────────────────────────────────────


@celery_app.task(name="app.tasks.webhook_tasks.deliver_webhook")
def deliver_webhook(delivery_id: str) -> None:
    """Deliver a single webhook attempt and advance its row state.

    Synchronous Celery wrapper around :func:`_async_deliver_webhook`.
    The async body is run inside a fresh ``asyncio.run`` event loop on
    every invocation so each delivery owns its own
    :class:`httpx.AsyncClient`, its own database session, and its own
    transaction boundary. The task is idempotent on a per-row basis:
    if the row is already in a terminal state when the task runs (for
    example because the reconciler raced with the original dispatch)
    the body returns without making an HTTP call.

    Args:
        delivery_id: UUID string of the
            :class:`~app.models.webhook_delivery.WebhookDelivery` row
            to deliver.
    """
    asyncio.run(_async_deliver_webhook(delivery_id))


@celery_app.task(name="app.tasks.webhook_tasks.reconcile_pending_deliveries")
def reconcile_pending_deliveries() -> None:
    """Re-enqueue ``pending`` deliveries older than 60 seconds.

    Synchronous Celery wrapper around :func:`_async_reconcile`. Designed
    to run on Celery beat every five minutes so that a delivery row
    whose original Celery enqueue was lost (e.g., the API-side broker
    write failed at dispatch time) eventually progresses. Re-enqueue
    failures are logged and skipped; the next reconciler tick will
    retry.
    """
    asyncio.run(_async_reconcile())


@celery_app.task(
    name="app.tasks.webhook_tasks.invalidate_previous_secret",
    bind=True,
    max_retries=10,
    default_retry_delay=60,
)
def invalidate_previous_secret(self, subscription_id: str) -> None:
    """Clear ``previous_secret_hash`` after the rotation grace window.

    Called via ``apply_async(countdown=PREVIOUS_SECRET_GRACE_SECONDS)``
    from the rotate-secret route. Marks the previous secret invalid by
    setting ``previous_secret_hash = None`` for the subscription so the
    delivery worker stops accepting it as a fallback signing key
    (Req 3 AC5).

    At-least-once semantics: if any database error occurs the task
    re-raises through Celery's ``self.retry(exc=...)`` up to
    ``max_retries=10`` times with exponential backoff (60 s base
    doubled per retry). If the row is already ``None`` (because the
    subscription was rotated again or invalidation already ran), the
    update is a no-op and the task succeeds — this is safe under
    at-least-once delivery because two concurrent invalidations both
    converge on the same final state.

    Args:
        subscription_id: The subscription whose previous secret hash
            should be cleared.
    """
    asyncio.run(_async_invalidate_previous_secret(self, subscription_id))


# ── Async bodies ──────────────────────────────────────────────────────


async def _async_deliver_webhook(delivery_id: str) -> None:
    """Async body: load row, POST, classify, schedule retry or terminate.

    Opens a fresh :class:`AsyncSession` so the worker does not depend on
    any FastAPI request scope. The session is committed exactly once at
    the end of the body so all row mutations and the audit emission
    land atomically. If an unexpected exception escapes the HTTP path,
    the session is rolled back and the exception is re-raised so Celery
    surfaces it on the result backend; the delivery row is left in
    whatever state it had on entry, and the reconciler will pick it up
    again.

    Args:
        delivery_id: UUID string of the delivery row to deliver.
    """
    # Local imports keep the Celery task module importable even when the
    # worker process boots before the ORM models module is fully loaded.
    from ..models.webhook_delivery import WebhookDelivery
    from ..models.webhook_subscription import WebhookSubscription

    async with async_session() as db:
        delivery = await db.get(WebhookDelivery, delivery_id)
        if delivery is None:
            logger.warning(
                "WebhookDelivery %s not found; abandoning task", delivery_id
            )
            return

        if delivery.status in ("succeeded", "failed_permanent"):
            # Reconciler raced with original dispatch, or a duplicate
            # was enqueued. The terminal state is authoritative.
            return

        sub = await db.get(WebhookSubscription, delivery.subscription_id)
        if sub is None or not sub.active:
            # Subscription was deleted (cascades to delivery, so this is
            # rare) or soft-deleted between enqueue and dispatch. Mark
            # the row terminal so the reconciler does not loop on it.
            await _terminate_failed(
                db,
                delivery=delivery,
                subscription=sub,
                response_status=None,
                error_message="subscription_inactive",
            )
            await db.commit()
            return

        # Build the canonical body and signature using the plaintext
        # signing secret stored in the (misnamed) ``signing_secret_hash``
        # column; see the module docstring for the rationale.
        body_bytes = canonical_body_bytes(delivery.payload)
        signature_header = sign(
            secret=sub.signing_secret_hash, body_bytes=body_bytes
        )
        headers = build_delivery_headers(
            event_type=delivery.event_type,
            delivery_id=delivery.id,
            signature_header=signature_header,
        )

        delivery.last_attempt_at = datetime.now(timezone.utc)

        response_status: Optional[int] = None
        error_message: Optional[str] = None
        try:
            timeout = httpx.Timeout(
                float(settings.webhook_delivery_timeout_seconds)
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    sub.target_url,
                    content=body_bytes,
                    headers=headers,
                )
            response_status = resp.status_code
        except httpx.TimeoutException as exc:
            error_message = _truncate(f"timeout: {exc}")
        except httpx.HTTPError as exc:
            error_message = _truncate(f"network_error: {exc}")
        except Exception as exc:  # noqa: BLE001 — defensive backstop
            # Anything outside the httpx exception tree (e.g., DNS edge
            # cases on some platforms surface as OSError directly) is
            # treated as a network error. Re-raising would let Celery
            # retry blindly without advancing ``attempt_count``, which
            # would defeat the row-driven retry counter.
            error_message = _truncate(f"network_error: {exc}")

        # Classify outcome and apply the row-state transition.
        if response_status is not None and 200 <= response_status <= 299:
            await _terminate_succeeded(
                db,
                delivery=delivery,
                subscription=sub,
                response_status=response_status,
            )
            await db.commit()
            return

        # Failure path: increment the row counter first so the schedule
        # index is "attempts already made minus one".
        delivery.attempt_count = (delivery.attempt_count or 0) + 1
        delivery.last_response_status = response_status
        if error_message is not None:
            delivery.last_error = error_message
        elif response_status is not None:
            delivery.last_error = _truncate(
                f"http_{response_status}: non-2xx response"
            )

        schedule = settings.webhook_retry_schedule_seconds
        max_attempts = len(schedule)

        if delivery.attempt_count >= max_attempts:
            # Fifth failed attempt — terminal failure (Req 4.6).
            await _terminate_failed(
                db,
                delivery=delivery,
                subscription=sub,
                response_status=response_status,
                error_message=delivery.last_error,
            )
            await db.commit()
            return

        # Schedule the next attempt. The countdown is read from the
        # tuple by (attempts already made - 1); index bounds were just
        # checked.
        countdown = int(schedule[delivery.attempt_count - 1])
        next_attempt_at = datetime.now(timezone.utc) + timedelta(
            seconds=countdown
        )
        delivery.status = "retrying"
        delivery.next_attempt_at = next_attempt_at

        try:
            celery_app.send_task(
                "app.tasks.webhook_tasks.deliver_webhook",
                args=[delivery.id],
                queue="webhooks",
                countdown=countdown,
            )
        except Exception as enqueue_exc:  # noqa: BLE001
            # Per Req 4.7: retry-scheduling failure is itself terminal.
            error_text = _truncate(
                f"retry_enqueue_failed: {type(enqueue_exc).__name__}: "
                f"{enqueue_exc}"
            )
            await _terminate_failed(
                db,
                delivery=delivery,
                subscription=sub,
                response_status=response_status,
                error_message=error_text,
            )
            await db.commit()
            return

        # Non-terminal commit: persist the retry intent.
        await db.commit()


async def _async_reconcile() -> None:
    """Find ``pending`` deliveries older than the threshold and re-enqueue.

    Reads the row ids in a short read-only transaction, then closes the
    session before issuing Celery enqueues so a slow broker does not
    hold a database connection. Each enqueue is independently
    try/except so a transient broker error on one id does not abort
    the rest of the batch.
    """
    from ..models.webhook_delivery import WebhookDelivery

    threshold = datetime.now(timezone.utc) - timedelta(
        seconds=_RECONCILE_PENDING_AGE_SECONDS
    )

    async with async_session() as db:
        result = await db.execute(
            select(WebhookDelivery.id).where(
                WebhookDelivery.status == "pending",
                WebhookDelivery.created_at < threshold,
            )
        )
        ids: List[str] = list(result.scalars().all())

    for did in ids:
        try:
            celery_app.send_task(
                "app.tasks.webhook_tasks.deliver_webhook",
                args=[did],
                queue="webhooks",
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Reconciler enqueue failed for delivery %s; "
                "next tick will retry",
                did,
            )


# ── Internal helpers ──────────────────────────────────────────────────


def _truncate(text: str) -> str:
    """Truncate a string to fit ``WebhookDelivery.last_error``.

    The model column is ``Text`` and accepts arbitrary length, but the
    delivery-history UI and audit ``details`` are bounded by the
    1000-char convention used elsewhere in the platform.

    Args:
        text: Possibly long error description.

    Returns:
        ``text`` truncated to at most :data:`_LAST_ERROR_MAX_CHARS`.
    """
    if len(text) <= _LAST_ERROR_MAX_CHARS:
        return text
    return text[:_LAST_ERROR_MAX_CHARS]


async def _terminate_succeeded(
    db,
    *,
    delivery,
    subscription,
    response_status: int,
) -> None:
    """Apply the ``succeeded`` terminal transition.

    Updates the delivery row, refreshes the subscription's denormalized
    last-delivery cache, and emits a single
    ``webhook.delivery.succeeded`` audit row. The caller is responsible
    for committing the transaction.

    Args:
        db: Active async database session.
        delivery: The :class:`WebhookDelivery` row being terminated.
        subscription: The owning :class:`WebhookSubscription`.
        response_status: The 2xx HTTP status code from the receiver.
    """
    now = datetime.now(timezone.utc)
    delivery.status = "succeeded"
    delivery.completed_at = now
    delivery.last_response_status = response_status
    delivery.last_error = None
    delivery.next_attempt_at = None
    if delivery.attempt_count == 0:
        # Increment so the row reflects the attempt that just succeeded.
        delivery.attempt_count = 1

    subscription.last_delivery_at = now
    subscription.last_delivery_status = "succeeded"

    await log_audit(
        db,
        action="webhook.delivery.succeeded",
        user_id=subscription.user_id,
        resource_type="webhook_delivery",
        resource_id=delivery.id,
        details={
            "subscription_id": subscription.id,
            "event_type": delivery.event_type,
            "attempt_count": delivery.attempt_count,
            "last_response_status": response_status,
        },
    )


async def _terminate_failed(
    db,
    *,
    delivery,
    subscription,
    response_status: Optional[int],
    error_message: Optional[str],
) -> None:
    """Apply the ``failed_permanent`` terminal transition.

    Updates the delivery row, refreshes the subscription's
    denormalized last-delivery cache when the subscription still
    exists, and emits a single ``webhook.delivery.failed`` audit row.
    The caller is responsible for committing the transaction.

    Args:
        db: Active async database session.
        delivery: The :class:`WebhookDelivery` row being terminated.
        subscription: The owning :class:`WebhookSubscription`, or
            ``None`` if the subscription was deleted between enqueue
            and dispatch.
        response_status: HTTP status from the most recent attempt, or
            ``None`` for network / timeout / scheduling failures.
        error_message: Truncated error description (already passed
            through :func:`_truncate`).
    """
    now = datetime.now(timezone.utc)
    delivery.status = "failed_permanent"
    delivery.completed_at = now
    delivery.last_response_status = response_status
    delivery.last_error = error_message
    delivery.next_attempt_at = None

    if subscription is not None:
        subscription.last_delivery_at = now
        subscription.last_delivery_status = "failed_permanent"

    await log_audit(
        db,
        action="webhook.delivery.failed",
        user_id=subscription.user_id if subscription is not None else None,
        resource_type="webhook_delivery",
        resource_id=delivery.id,
        details={
            "subscription_id": delivery.subscription_id,
            "event_type": delivery.event_type,
            "attempt_count": delivery.attempt_count,
            "last_response_status": response_status,
            "last_error": error_message,
        },
    )


async def _async_invalidate_previous_secret(
    task_ctx, subscription_id: str
) -> None:
    """Async body: clear ``previous_secret_hash`` with at-least-once retry.

    Issues a single ``UPDATE webhook_subscriptions SET
    previous_secret_hash = NULL WHERE id = :sub_id``. The statement is
    naturally idempotent — if the column is already ``None`` because a
    later rotation cleared it or a previous invalidation already ran,
    the row count is zero and the task still succeeds. On any
    exception during the write the task asks Celery to retry with
    exponential backoff (60 s base, doubled per retry, capped by
    ``max_retries=10`` on the bound task), preserving at-least-once
    semantics.

    Args:
        task_ctx: The bound Celery task instance (``self`` from the
            wrapper) used to call :meth:`Task.retry` and surface
            ``MaxRetriesExceededError`` if the retry budget is
            exhausted.
        subscription_id: The subscription whose previous secret hash
            should be cleared.
    """
    from sqlalchemy import update

    from ..models.webhook_subscription import WebhookSubscription

    try:
        async with async_session() as db:
            await db.execute(
                update(WebhookSubscription)
                .where(WebhookSubscription.id == subscription_id)
                .values(previous_secret_hash=None)
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — retry on any DB error
        try:
            raise task_ctx.retry(
                exc=exc,
                countdown=60 * (2 ** task_ctx.request.retries),
            )
        except task_ctx.MaxRetriesExceededError:
            logger.exception(
                "Max retries exceeded for invalidate_previous_secret(%s)",
                subscription_id,
            )

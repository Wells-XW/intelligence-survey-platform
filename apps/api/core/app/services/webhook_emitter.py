"""Domain event emitter for webhook fan-out.

This module is the single entry point that domain code calls when a
subscribed event has occurred. It performs the matching query against
``webhook_subscriptions``, inserts one ``WebhookDelivery`` per match in
status ``pending`` inside the caller's existing transaction, and exposes
a separate helper :func:`enqueue_webhook_deliveries` that the caller
must invoke *after* committing so a Celery worker does not race with an
as-yet-uncommitted delivery row.

Permission gating mirrors the design contract (see
``.kiro/specs/api-platform-export/design.md`` Component 3): a
subscription only receives an event when its owner has at least viewer
permission on the event's ``survey_id``. Subscriptions whose
``survey_id`` is set must additionally match the event's ``survey_id``;
subscriptions whose ``survey_id`` is ``None`` (account-scoped) match
every survey the owner can see.

This module deliberately does not commit. The caller controls the
transaction boundary because emit is one of several writes in a single
business operation (e.g. submitting a survey response also writes a
``SurveyResponse`` row and may bump quotas).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.survey_permission import SurveyPermission
from ..models.webhook_delivery import WebhookDelivery
from ..models.webhook_subscription import WebhookSubscription

logger = logging.getLogger(__name__)


async def emit_webhook_event(
    db: AsyncSession,
    *,
    event_type: str,
    survey_id: Optional[str],
    payload: Dict[str, Any],
) -> List[str]:
    """Fan out one domain event to all matching active subscriptions.

    The caller is responsible for committing the surrounding transaction.
    Newly inserted ``WebhookDelivery`` rows are flushed but not committed,
    so a downstream rollback (e.g. a quota update failure later in the
    same handler) cleanly removes the deliveries along with the rest of
    the operation.

    Args:
        db: Active database session whose transaction the caller owns.
        event_type: Canonical event label, one of ``response.created``,
            ``response.completed``, ``quota.reached``,
            ``distribution.sent``.
        survey_id: The survey associated with the event, or ``None`` for
            non-survey-scoped events. Used both for the permission gate
            and for filtering survey-scoped subscriptions.
        payload: JSON-serializable event body. Stored byte-for-byte on
            the delivery row so manual redelivery reproduces the
            original signature input.

    Returns:
        List of newly created ``WebhookDelivery`` row ids. Pass this to
        :func:`enqueue_webhook_deliveries` after the caller commits.
    """
    # Fetch all active subs whose event_types JSONB array contains
    # event_type. The downstream permission gate further filters this
    # candidate set.
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.active.is_(True),
        WebhookSubscription.event_types.contains([event_type]),
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())

    matching: List[WebhookSubscription] = []
    for sub in candidates:
        # Subscription scoped to a specific survey must match event's
        # survey_id exactly; account-scoped subs (sub.survey_id is None)
        # accept any survey.
        if sub.survey_id is not None and sub.survey_id != survey_id:
            continue

        # Permission gate. The target survey for the gate is the event's
        # survey_id (when set) — that's the survey whose data the
        # receiver is about to learn about.
        if survey_id is None:
            # No survey context on the event. Currently every
            # subscribed event type carries a survey_id, so this branch
            # is reserved for future account-scoped events; we accept
            # any account-scoped sub that asked for the event type.
            if sub.survey_id is None:
                matching.append(sub)
            continue

        perm_result = await db.execute(
            select(SurveyPermission).where(
                SurveyPermission.survey_id == survey_id,
                SurveyPermission.user_id == sub.user_id,
            )
        )
        if perm_result.scalar_one_or_none() is not None:
            matching.append(sub)

    delivery_ids: List[str] = []
    for sub in matching:
        delivery = WebhookDelivery(
            subscription_id=sub.id,
            event_type=event_type,
            payload=payload,
            status="pending",
            attempt_count=0,
        )
        db.add(delivery)
        await db.flush()
        delivery_ids.append(delivery.id)

    return delivery_ids


def enqueue_webhook_deliveries(delivery_ids: List[str]) -> None:
    """Enqueue Celery delivery tasks for the given delivery ids.

    Call this **after** the caller has committed so the Celery worker
    does not race with an as-yet-uncommitted delivery row. Failures are
    logged and swallowed; the in-flight reconciler (T15 design Task 8.1)
    sweeps stuck ``pending`` rows so a transient broker outage does not
    drop deliveries.

    Args:
        delivery_ids: Ids returned by :func:`emit_webhook_event`. Empty
            list is a no-op.
    """
    if not delivery_ids:
        return
    try:
        from ..tasks import celery_app
    except Exception:  # pragma: no cover — celery import failure
        logger.exception("Failed to import celery_app for webhook enqueue")
        return
    for delivery_id in delivery_ids:
        try:
            celery_app.send_task(
                "app.tasks.webhook_tasks.deliver_webhook",
                args=[delivery_id],
                queue="webhooks",
            )
        except Exception:
            logger.exception(
                "Failed to enqueue webhook delivery %s", delivery_id
            )

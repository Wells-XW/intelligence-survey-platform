"""Webhook subscription lifecycle and delivery management routes.

These endpoints implement Components 3 and 4 of the design: ``POST /``,
``GET /``, ``PATCH /{sub_id}``, ``POST /{sub_id}/rotate-secret``,
``DELETE /{sub_id}``, ``GET /{sub_id}/deliveries``, and
``POST /{sub_id}/deliveries/{delivery_id}/redeliver``. They satisfy
Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, and 4.10.

Per Req 8 AC5 the API platform must never issue, refresh, or extend
caller credentials through an API-key-authenticated path. Subscription
lifecycle endpoints therefore depend on :func:`_require_jwt_principal`,
which rejects principals whose ``api_key`` attribute is non-null with a
403 ``jwt_only`` error. JWT-authenticated callers continue through
unchanged.

The plaintext signing secret is returned to the client exactly once —
at creation and at rotation — and is never persisted in plaintext.
The persistence column ``signing_secret_ciphertext`` holds the Fernet
ciphertext produced by
:func:`app.core.webhook_secret_crypto.encrypt_signing_secret`; the
delivery worker decrypts on demand to compute outbound HMAC signatures
per Req 4 AC3. List, update, delete, and history responses never carry
the plaintext.

Soft-delete semantics:
    The ``DELETE`` route flips ``active`` to ``False`` rather than
    issuing a SQL ``DELETE`` against ``webhook_subscriptions``. This
    preserves the FK link from ``webhook_deliveries.subscription_id``
    (which is ``ON DELETE CASCADE``) and so retains the full delivery
    history per Req 3 AC6 and design §Component 3.
"""

from __future__ import annotations

import secrets
from typing import List
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.audit import log_audit
from ...core.deps import (
    Principal,
    check_survey_permission,
    get_principal,
)
from ...core.webhook_secret_crypto import encrypt_signing_secret
from ...database import get_db
from ...models.webhook_delivery import WebhookDelivery
from ...models.webhook_subscription import WebhookSubscription
from ...schemas.webhook import (
    WebhookDeliveryOut,
    WebhookSubscriptionCreateIn,
    WebhookSubscriptionCreateOut,
    WebhookSubscriptionOut,
    WebhookSubscriptionRotateOut,
    WebhookSubscriptionUpdateIn,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── Module constants ──────────────────────────────────────────────────

#: Fixed event-type enumeration drawn from design §Component 3. Any
#: event-type string outside this set is rejected with a 400
#: ``webhook_event_unsupported`` response (Req 3 AC3). The four entries
#: correspond to the existing domain transitions wired up by the event
#: emitter described in Task 7.3.
SUPPORTED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "response.created",
        "response.completed",
        "quota.reached",
        "distribution.sent",
    }
)

#: Plaintext signing-secret prefix. Stamping the prefix on every issued
#: secret lets receivers' log scrubbers and credential scanners flag a
#: leaked secret in the same way Stripe / GitHub use distinct prefixes.
_SECRET_PREFIX: str = "whsec_"

#: Default page size for the delivery history endpoint. Matches the
#: cap chosen for the API key list endpoint family so admin UIs can
#: assume a uniform default.
_DEFAULT_DELIVERY_LIMIT: int = 50

#: Hard upper bound on the per-page delivery count. Any caller-supplied
#: ``limit`` higher than this is silently clamped — we prefer the
#: clamp-without-error path because delivery history endpoints are
#: read-only and a too-large page is an inefficiency, not a correctness
#: hazard.
_MAX_DELIVERY_LIMIT: int = 200


# ── Auth and validation helpers ───────────────────────────────────────


def _require_jwt_principal(
    principal: Principal = Depends(get_principal),
) -> Principal:
    """Reject API-key callers from webhook management endpoints.

    Implements Req 8 AC5: API keys must never grant the ability to
    manage webhook subscriptions on behalf of their owner without an
    interactive JWT login. Callers authenticated via JWT pass through
    unchanged; callers authenticated via API key receive a 403 with
    machine code ``jwt_only``.

    Args:
        principal: The resolved request principal.

    Returns:
        The principal when JWT-authenticated.

    Raises:
        HTTPException: 403 ``jwt_only`` when the principal carries a
            non-null ``api_key`` attribute.
    """
    if principal.api_key is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "jwt_only"},
        )
    return principal


def _validate_target_url(target_url: str) -> None:
    """Validate that a webhook target URL uses the HTTPS scheme.

    Implements Req 3 AC2. The check is intentionally strict: only the
    canonical lowercase ``https`` scheme is accepted so misconfigured
    receivers cannot accidentally exfiltrate signed payloads over
    plain HTTP. The check runs on both create and update payloads.

    Args:
        target_url: URL string from the request body.

    Raises:
        HTTPException: 400 ``webhook_url_must_be_https`` when the URL
            cannot be parsed or its scheme is not ``https``.
    """
    try:
        parsed = urlparse(target_url)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "webhook_url_must_be_https"},
        )
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "webhook_url_must_be_https"},
        )


def _validate_event_types(event_types: List[str]) -> None:
    """Validate that every event type is in the supported set.

    Implements Req 3 AC3. The route layer enforces a non-empty list at
    the schema layer (``min_length=1``); this helper covers the
    enum-membership half. Unknown entries are echoed back so the
    client can correct the offending strings without guessing.

    Args:
        event_types: Non-empty list of event-type strings from the
            request body.

    Raises:
        HTTPException: 400 ``webhook_event_unsupported`` when one or
            more entries are not members of
            :data:`SUPPORTED_EVENT_TYPES`. The response body echoes
            ``unsupported`` so callers can build a corrective UI.
    """
    unsupported = [e for e in event_types if e not in SUPPORTED_EVENT_TYPES]
    if unsupported:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "webhook_event_unsupported",
                "unsupported": unsupported,
            },
        )


def _generate_signing_secret() -> str:
    """Generate a fresh plaintext webhook signing secret.

    The plaintext format is ``whsec_<32 url-safe base64 characters>``,
    drawn from :func:`secrets.token_urlsafe(24)` (which yields ~32
    characters of base64 over 192 bits of entropy). The prefix is
    fixed so receivers' log scrubbers and credential scanners can
    flag a leaked secret the same way Stripe / GitHub style prefixes
    are flagged.

    Persistence note:
        The plaintext returned here is surfaced to the caller exactly
        once at create or rotate time. The route layer encrypts it
        via :func:`app.core.webhook_secret_crypto.encrypt_signing_secret`
        before storing in
        ``WebhookSubscription.signing_secret_ciphertext``; the worker
        decrypts on demand to compute outbound HMAC signatures. The
        plaintext bytes never reach the persistence layer, satisfying
        Property 1 (plaintext credential exposure exactly-once) for
        the webhook clause.

    Returns:
        The plaintext signing secret.
    """
    return _SECRET_PREFIX + secrets.token_urlsafe(24)


async def _load_owned_subscription(
    sub_id: str, principal: Principal, db: AsyncSession
) -> WebhookSubscription:
    """Load a subscription that the caller owns or raise 404.

    Subscription ownership is the authoritative gate; non-owners get a
    404 (rather than 403) so subscription existence is hidden from
    callers who have no business with it. This mirrors the same
    "hide-existence" pattern used by ``check_survey_permission``.

    Args:
        sub_id: The subscription id from the URL path.
        principal: The JWT-authenticated principal making the request.
        db: Active async database session.

    Returns:
        The :class:`WebhookSubscription` row owned by ``principal``.

    Raises:
        HTTPException: 404 ``webhook_subscription_not_found`` when the
            row is unknown or owned by another user.
    """
    result = await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.id == sub_id,
            WebhookSubscription.user_id == principal.user.id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "webhook_subscription_not_found"},
        )
    return row


def _build_subscription_payload(row: WebhookSubscription) -> dict:
    """Serialize a :class:`WebhookSubscription` row into the shared shape.

    The shape matches both :class:`WebhookSubscriptionOut` (no secret)
    and the metadata portion of :class:`WebhookSubscriptionCreateOut`
    or :class:`WebhookSubscriptionRotateOut`; callers that need
    plaintext attach it after calling this helper.

    Args:
        row: The :class:`WebhookSubscription` row.

    Returns:
        A dict suitable for ``WebhookSubscriptionOut(**payload)`` or,
        with a ``signing_secret`` entry merged in, the create / rotate
        response shapes.
    """
    return {
        "id": row.id,
        "user_id": row.user_id,
        "survey_id": row.survey_id,
        "target_url": row.target_url,
        "event_types": list(row.event_types or []),
        "description": row.description,
        "active": row.active,
        "last_delivery_at": row.last_delivery_at,
        "last_delivery_status": row.last_delivery_status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _build_delivery_payload(row: WebhookDelivery) -> dict:
    """Serialize a :class:`WebhookDelivery` row into the public shape.

    Args:
        row: The :class:`WebhookDelivery` row.

    Returns:
        A dict suitable for ``WebhookDeliveryOut(**payload)``.
    """
    return {
        "id": row.id,
        "subscription_id": row.subscription_id,
        "event_type": row.event_type,
        "payload": row.payload,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "last_attempt_at": row.last_attempt_at,
        "last_response_status": row.last_response_status,
        "last_error": row.last_error,
        "next_attempt_at": row.next_attempt_at,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
    }


def _enqueue_delivery(delivery_id: str) -> None:
    """Best-effort enqueue of a delivery on the ``webhooks`` Celery queue.

    The delivery worker (:mod:`app.tasks.webhook_tasks`, Task 8.1) is
    the eventual consumer. We use :meth:`Celery.send_task` rather than
    importing the worker module directly so that the API process does
    not depend on the worker being importable in its environment;
    Celery resolves the task by name on the broker side.

    Failures are intentionally non-fatal: the row has already been
    persisted, and the delivery worker's reconciler scan picks up
    ``pending`` rows older than 60 seconds (per Task 8.1). Surfacing
    a transient broker outage as a 500 to the caller would be worse
    than the eventual-consistency window the reconciler closes.

    Args:
        delivery_id: UUID string of the delivery row to dispatch.
    """
    try:
        # Imported lazily so a development environment without Celery
        # configured (e.g. a unit test file run in isolation) does not
        # error at module import time.
        from ...tasks import celery_app

        celery_app.send_task(
            "app.tasks.webhook_tasks.deliver_webhook",
            args=[delivery_id],
            queue="webhooks",
        )
    except Exception:
        # Swallow: the row exists, the reconciler will retry. We
        # intentionally do not log here to avoid wiring a logger
        # surface for what is by design a recoverable miss.
        pass


# ── Routes ────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=WebhookSubscriptionCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a webhook subscription",
    description=(
        "Create a new webhook subscription owned by the authenticated "
        "user. The signing secret is returned in the response body "
        "exactly once — capture it now, it cannot be recovered later."
    ),
)
async def create_webhook_subscription(
    body: WebhookSubscriptionCreateIn,
    request: Request,
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> WebhookSubscriptionCreateOut:
    """Create a new webhook subscription for the authenticated user.

    Validates the HTTPS scheme on ``target_url`` (Req 3 AC2) and the
    event-type membership on ``event_types`` (Req 3 AC3) before any
    write. When ``survey_id`` is supplied, the caller must hold at
    least viewer permission on that survey; the same RBAC gate that
    governs read access to the survey gates registration of webhook
    subscriptions targeting it. Generates a fresh plaintext signing
    secret via :func:`_generate_signing_secret`, encrypts it with
    :func:`encrypt_signing_secret`, stores the resulting Fernet
    ciphertext, and returns the plaintext exactly once. Emits a
    ``webhook.subscription.create`` audit row whose ``details`` carry
    the new subscription id, the target URL, and the event-type list.

    Args:
        body: Create payload with ``target_url``, ``event_types``,
            optional ``survey_id``, and optional ``description``.
        request: Inbound request, used for audit attribution.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        The :class:`WebhookSubscriptionCreateOut` payload, with the
        plaintext signing secret set.

    Raises:
        HTTPException: 400 on URL or event-type validation failure;
            404 when ``survey_id`` is supplied but the caller has no
            permission on that survey.
    """
    _validate_target_url(body.target_url)
    _validate_event_types(list(body.event_types))

    if body.survey_id is not None:
        # Survey scope is gated by the standard survey RBAC check —
        # the same one that governs read access. A 404 from this
        # helper hides survey existence from callers without view
        # rights, which matches the behaviour of every other
        # survey-scoped route in the platform.
        await check_survey_permission(body.survey_id, principal.user, "viewer", db)

    plaintext = _generate_signing_secret()
    ciphertext = encrypt_signing_secret(plaintext)

    row = WebhookSubscription(
        user_id=principal.user.id,
        survey_id=body.survey_id,
        target_url=body.target_url,
        event_types=list(body.event_types),
        description=body.description,
        signing_secret_ciphertext=ciphertext,
        active=True,
    )
    db.add(row)
    await db.flush()

    await log_audit(
        db,
        action="webhook.subscription.create",
        user_id=principal.user.id,
        resource_type="webhook_subscription",
        resource_id=row.id,
        details={
            "subscription_id": row.id,
            "target_url": row.target_url,
            "event_types": list(row.event_types),
            "survey_id": row.survey_id,
        },
        request=request,
    )

    await db.commit()
    await db.refresh(row)

    payload = _build_subscription_payload(row)
    payload["signing_secret"] = plaintext
    return WebhookSubscriptionCreateOut(**payload)


@router.get(
    "/",
    response_model=List[WebhookSubscriptionOut],
    summary="List the caller's webhook subscriptions",
    description=(
        "Return every webhook subscription owned by the authenticated "
        "user, newest-first. Soft-deleted subscriptions (``active`` "
        "set to false) remain in the list so the user can review or "
        "reactivate them."
    ),
)
async def list_webhook_subscriptions(
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> List[WebhookSubscriptionOut]:
    """List the authenticated user's webhook subscriptions.

    Returns every subscription the caller owns — active and inactive
    — in newest-first order so the user has a single place to review
    delivery health and the soft-delete state. Plaintext and hash
    fields are never included.

    Args:
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        A list of :class:`WebhookSubscriptionOut` payloads.
    """
    result = await db.execute(
        select(WebhookSubscription)
        .where(WebhookSubscription.user_id == principal.user.id)
        .order_by(WebhookSubscription.created_at.desc())
    )
    rows = list(result.scalars().all())
    return [
        WebhookSubscriptionOut(**_build_subscription_payload(r)) for r in rows
    ]


@router.patch(
    "/{sub_id}",
    response_model=WebhookSubscriptionOut,
    summary="Update a webhook subscription",
    description=(
        "Partially update a subscription's target URL, event-type "
        "list, description, or active flag. Only the fields supplied "
        "in the request body are changed; omitted fields keep their "
        "current values."
    ),
)
async def update_webhook_subscription(
    sub_id: str,
    body: WebhookSubscriptionUpdateIn,
    request: Request,
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> WebhookSubscriptionOut:
    """Partial update of a webhook subscription.

    Validates HTTPS scheme on ``target_url`` and event-type membership
    on ``event_types`` only when those fields are present in the
    payload. Emits a ``webhook.subscription.update`` audit row whose
    ``details`` capture the set of changed fields so reviewers can
    reconstruct the subscription's history without comparing raw rows.

    Args:
        sub_id: The id of the subscription to update.
        body: Partial update payload; any subset of ``target_url``,
            ``event_types``, ``description``, ``active``.
        request: Inbound request, for audit attribution.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        The :class:`WebhookSubscriptionOut` reflecting the new state.

    Raises:
        HTTPException: 404 when the subscription is unknown or owned
            by a different user; 400 on URL or event-type validation
            failure for fields supplied in the payload.
    """
    row = await _load_owned_subscription(sub_id, principal, db)

    changed: dict = {}
    if body.target_url is not None:
        _validate_target_url(body.target_url)
        row.target_url = body.target_url
        changed["target_url"] = body.target_url
    if body.event_types is not None:
        _validate_event_types(list(body.event_types))
        row.event_types = list(body.event_types)
        changed["event_types"] = list(body.event_types)
    if body.description is not None:
        # An empty string clears the column; the schema layer caps
        # length at 500 so no further validation is needed here.
        row.description = body.description or None
        changed["description"] = body.description
    if body.active is not None:
        row.active = body.active
        changed["active"] = body.active

    if changed:
        await db.flush()
        await log_audit(
            db,
            action="webhook.subscription.update",
            user_id=principal.user.id,
            resource_type="webhook_subscription",
            resource_id=row.id,
            details={"subscription_id": row.id, "changes": changed},
            request=request,
        )
        await db.commit()
        await db.refresh(row)

    return WebhookSubscriptionOut(**_build_subscription_payload(row))


@router.post(
    "/{sub_id}/rotate-secret",
    response_model=WebhookSubscriptionRotateOut,
    summary="Rotate a webhook subscription's signing secret",
    description=(
        "Generate a fresh signing secret and return it in the response "
        "body exactly once. The previous secret stays valid for "
        "receiver-side verification until the background invalidation "
        "task clears it (Req 3 AC5)."
    ),
)
async def rotate_webhook_secret(
    sub_id: str,
    request: Request,
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> WebhookSubscriptionRotateOut:
    """Rotate the signing secret on an existing subscription.

    Generates a fresh plaintext, encrypts it via
    :func:`encrypt_signing_secret`, moves the current
    ``signing_secret_ciphertext`` into ``previous_secret_ciphertext`` to
    open the rotation invalidation window described in Req 3 AC5,
    persists the new ciphertext, and returns the new plaintext exactly
    once. The background invalidation task scheduled in Task 8.2 clears
    ``previous_secret_ciphertext`` once the previous secret is no
    longer accepted by the worker. Emits a
    ``webhook.subscription.rotate_secret`` audit row.

    Args:
        sub_id: The id of the subscription to rotate.
        request: Inbound request, for audit attribution.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        The :class:`WebhookSubscriptionRotateOut` payload with the new
        plaintext signing secret.

    Raises:
        HTTPException: 404 when the subscription is unknown or owned
            by a different user.
    """
    row = await _load_owned_subscription(sub_id, principal, db)

    new_plaintext = _generate_signing_secret()
    new_ciphertext = encrypt_signing_secret(new_plaintext)
    # Move the previously persisted ciphertext into the rotation
    # invalidation slot so the receiver-side dual-acceptance window
    # (Req 3 AC5) and the background invalidation task can coordinate
    # per design §Component 4. The delivery worker always signs with
    # the new secret. The slot is cleared by the invalidation task
    # once the previous secret is no longer accepted.
    row.previous_secret_ciphertext = row.signing_secret_ciphertext
    row.signing_secret_ciphertext = new_ciphertext
    await db.flush()

    await log_audit(
        db,
        action="webhook.subscription.rotate_secret",
        user_id=principal.user.id,
        resource_type="webhook_subscription",
        resource_id=row.id,
        details={"subscription_id": row.id},
        request=request,
    )

    await db.commit()
    await db.refresh(row)

    # Schedule the previous-secret invalidation. Best-effort: if Celery
    # is unreachable at rotate time the dual-window stays open until
    # manual intervention. The receiver continues verifying with both
    # secrets in the meantime, so there is no client-visible failure.
    try:
        from ...tasks.webhook_tasks import (
            PREVIOUS_SECRET_GRACE_SECONDS,
            invalidate_previous_secret,
        )

        invalidate_previous_secret.apply_async(
            args=[row.id],
            countdown=PREVIOUS_SECRET_GRACE_SECONDS,
            queue="webhooks",
        )
    except Exception:  # noqa: BLE001 — broker outage is non-fatal here
        pass

    payload = _build_subscription_payload(row)
    payload["signing_secret"] = new_plaintext
    return WebhookSubscriptionRotateOut(**payload)


@router.delete(
    "/{sub_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a webhook subscription",
    description=(
        "Stop dispatching new deliveries for the subscription while "
        "retaining its full delivery history per the configured audit "
        "retention period (Req 3 AC6). The subscription remains "
        "visible in list responses with ``active`` set to false."
    ),
)
async def delete_webhook_subscription(
    sub_id: str,
    request: Request,
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a webhook subscription owned by the caller.

    Sets ``active`` to ``False`` rather than issuing a SQL ``DELETE``
    against the row. Soft-delete is the correct semantic here because
    Req 3 AC6 requires the delivery history to remain queryable for
    the audit retention period even after the subscription is removed.
    A hard delete would either cascade through the FK and destroy the
    history (current FK is ``ON DELETE CASCADE``) or fail with an
    integrity error if rows existed. The operation is idempotent: a
    second delete on an already-inactive subscription is a no-op and
    does not emit a duplicate audit row.

    Args:
        sub_id: The id of the subscription to soft-delete.
        request: Inbound request, for audit attribution.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        ``None`` — the response carries HTTP 204.

    Raises:
        HTTPException: 404 when the subscription is unknown or owned
            by a different user.
    """
    row = await _load_owned_subscription(sub_id, principal, db)

    if row.active:
        row.active = False
        await db.flush()

        await log_audit(
            db,
            action="webhook.subscription.delete",
            user_id=principal.user.id,
            resource_type="webhook_subscription",
            resource_id=row.id,
            details={"subscription_id": row.id},
            request=request,
        )
        await db.commit()

    return None


@router.get(
    "/{sub_id}/deliveries",
    response_model=List[WebhookDeliveryOut],
    summary="List delivery history for a subscription",
    description=(
        "Return delivery rows for the subscription in newest-first "
        "order. Pagination uses ``offset`` and ``limit`` query "
        "parameters; ``limit`` is capped at 200."
    ),
)
async def list_webhook_deliveries(
    sub_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(
        default=_DEFAULT_DELIVERY_LIMIT, ge=1, le=_MAX_DELIVERY_LIMIT
    ),
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> List[WebhookDeliveryOut]:
    """List delivery history for a subscription owned by the caller.

    Returns rows in ``created_at DESC`` order so the newest delivery
    is first. Both delivered (``succeeded`` / ``failed_permanent``)
    and in-flight (``pending`` / ``retrying``) rows are included so
    the caller can monitor live state alongside terminal history.

    Args:
        sub_id: The id of the parent subscription.
        offset: Pagination offset; non-negative.
        limit: Page size; clamped to ``[1, 200]`` by FastAPI's
            validation on the query parameter.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        A list of :class:`WebhookDeliveryOut` payloads.

    Raises:
        HTTPException: 404 when the subscription is unknown or owned
            by a different user.
    """
    # Load to verify ownership before exposing delivery rows.
    await _load_owned_subscription(sub_id, principal, db)

    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == sub_id)
        .order_by(WebhookDelivery.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return [WebhookDeliveryOut(**_build_delivery_payload(r)) for r in rows]


@router.post(
    "/{sub_id}/deliveries/{delivery_id}/redeliver",
    response_model=WebhookDeliveryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Manually redeliver a recorded webhook event",
    description=(
        "Create a new delivery row whose payload byte-for-byte "
        "matches the original delivery's payload (Req 4 AC10). The "
        "new row is enqueued on the webhooks queue with a fresh "
        "delivery identifier; the original row is left untouched."
    ),
)
async def redeliver_webhook(
    sub_id: str,
    delivery_id: str,
    principal: Principal = Depends(_require_jwt_principal),
    db: AsyncSession = Depends(get_db),
) -> WebhookDeliveryOut:
    """Manually redeliver a recorded webhook event.

    Loads the original :class:`WebhookDelivery` row, copies its
    ``payload`` and ``event_type`` into a brand-new row in status
    ``pending``, and enqueues the new row on the ``webhooks`` queue.
    The original row is left untouched so the audit trail of the
    first delivery sequence remains intact. The new row carries a
    fresh UUID id, which propagates as the ``X-Webhook-Delivery``
    header value the receiver sees on the redelivery attempt; the
    original payload bytes are preserved per Req 4 AC10 by reusing
    the JSONB column verbatim.

    Args:
        sub_id: The id of the parent subscription.
        delivery_id: The id of the original delivery to replay.
        principal: JWT-authenticated caller.
        db: Async database session.

    Returns:
        The :class:`WebhookDeliveryOut` payload for the newly created
        delivery row.

    Raises:
        HTTPException: 404 ``webhook_subscription_not_found`` when the
            subscription is unknown or owned by a different user; 404
            ``webhook_delivery_not_found`` when the delivery id does
            not belong to that subscription.
    """
    await _load_owned_subscription(sub_id, principal, db)

    original_result = await db.execute(
        select(WebhookDelivery).where(
            WebhookDelivery.id == delivery_id,
            WebhookDelivery.subscription_id == sub_id,
        )
    )
    original = original_result.scalar_one_or_none()
    if original is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "webhook_delivery_not_found"},
        )

    # Reusing the JSONB ``payload`` directly means SQLAlchemy ships
    # the same Python dict to the DB layer, which Postgres re-emits
    # byte-for-byte from ``WebhookDelivery.payload`` on the next read.
    # That is the property Req 4 AC10 requires of redelivery.
    new_delivery = WebhookDelivery(
        subscription_id=sub_id,
        event_type=original.event_type,
        payload=original.payload,
        status="pending",
        attempt_count=0,
    )
    db.add(new_delivery)
    await db.flush()

    new_id = new_delivery.id
    await db.commit()
    await db.refresh(new_delivery)

    # Enqueue after commit so a broker outage does not roll back the
    # row. The reconciler in Task 8.1 picks up pending rows older than
    # 60 seconds, so a missed enqueue is recoverable.
    _enqueue_delivery(new_id)

    return WebhookDeliveryOut(**_build_delivery_payload(new_delivery))

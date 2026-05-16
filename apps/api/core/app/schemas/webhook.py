"""Pydantic v2 schemas for the webhook subscription endpoints.

These schemas define the request and response shapes for the routes in
``app/api/v1/webhooks.py``. They are deliberately decoupled from the
:class:`app.models.webhook_subscription.WebhookSubscription` and
:class:`app.models.webhook_delivery.WebhookDelivery` ORM classes so that
documentation and serialization can evolve independently of the
database layer.

Plaintext-shown-once contract:
    The full signing secret value (``signing_secret``) is exposed only
    on the create-response shape (:class:`WebhookSubscriptionCreateOut`)
    and the rotate-response shape
    (:class:`WebhookSubscriptionRotateOut`). The list / detail shape
    (:class:`WebhookSubscriptionOut`) intentionally omits both the
    plaintext secret and its stored hash so callers cannot retrieve a
    secret after the moment it was issued. This shape boundary is the
    schema-level enforcement of Requirements 3.1, 3.4, and 3.7.

OpenAPI examples:
    Every schema attaches at least one realistic example payload via
    ``ConfigDict(json_schema_extra={"examples": [...]})`` so the
    auto-generated FastAPI documentation pages render concrete request
    and response bodies (Property 24, Requirement 1.4).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WebhookSubscriptionCreateIn(BaseModel):
    """Request body for ``POST /api/v1/webhooks``.

    The ``target_url`` field carries a full URL string rather than a
    Pydantic ``HttpUrl`` because the route layer applies an explicit
    HTTPS-only check that returns the spec-mandated machine code
    ``webhook_url_must_be_https`` (Req 3 AC2). Routing schema-level
    validation through Pydantic's URL parser would short-circuit that
    machine code with a generic ``url_parsing`` error.

    Attributes:
        target_url: Destination HTTPS URL the platform will POST events
            to. Must use the ``https://`` scheme.
        event_types: Non-empty list of event-type strings drawn from
            the fixed supported set ``{"response.created",
            "response.completed", "quota.reached",
            "distribution.sent"}``.
        survey_id: Optional survey scope. When ``None`` the
            subscription matches every survey the owner has at least
            viewer permission on (per design §Component 3).
        description: Optional human-readable label, up to 500
            characters to match the ORM column.
    """

    target_url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="HTTPS destination URL for outbound deliveries.",
        examples=["https://hooks.example.com/intelligence-survey"],
    )
    event_types: List[str] = Field(
        ...,
        min_length=1,
        description=(
            "Non-empty list of event-type strings drawn from the "
            "supported set."
        ),
        examples=[["response.created", "response.completed"]],
    )
    survey_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional survey scope. None matches every survey the "
            "owner can see."
        ),
        examples=["d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"],
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional human-readable label.",
        examples=["Reporting CRM follow-up integration"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "target_url": (
                        "https://hooks.example.com/intelligence-survey"
                    ),
                    "event_types": [
                        "response.created",
                        "response.completed",
                    ],
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "description": "Reporting CRM follow-up integration",
                }
            ]
        }
    )


class WebhookSubscriptionUpdateIn(BaseModel):
    """Request body for ``PATCH /api/v1/webhooks/{sub_id}``.

    All fields are optional. Fields the caller omits are left
    unchanged. The route layer re-runs the HTTPS-only and event-type
    enum validation on any field present in the payload.

    Attributes:
        target_url: New destination HTTPS URL, or ``None`` to leave
            unchanged.
        event_types: New event-type list, or ``None`` to leave
            unchanged. When supplied, must be non-empty.
        description: New description, or ``None`` to leave unchanged.
            Send an empty string to clear the existing description.
        active: New on/off toggle, or ``None`` to leave unchanged.
    """

    target_url: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="New HTTPS destination URL. Omit to leave unchanged.",
        examples=["https://hooks.example.com/intelligence-survey/v2"],
    )
    event_types: Optional[List[str]] = Field(
        default=None,
        min_length=1,
        description=(
            "New event-type list. Must be non-empty when supplied. "
            "Omit to leave unchanged."
        ),
        examples=[["response.completed", "quota.reached"]],
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description=(
            "New description. Send an empty string to clear. Omit to "
            "leave unchanged."
        ),
        examples=["Reporting CRM v2 integration"],
    )
    active: Optional[bool] = Field(
        default=None,
        description=(
            "New on/off toggle. Setting False stops new dispatches "
            "without removing delivery history."
        ),
        examples=[False],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "target_url": (
                        "https://hooks.example.com/intelligence-survey/v2"
                    ),
                    "event_types": [
                        "response.completed",
                        "quota.reached",
                    ],
                    "description": "Reporting CRM v2 integration",
                    "active": True,
                }
            ]
        }
    )


class WebhookSubscriptionOut(BaseModel):
    """Public-facing webhook subscription projection.

    Used by both the list endpoint and the detail-style projections
    embedded in create / update / rotate responses. Excludes both the
    plaintext signing secret and the stored hash so a caller can never
    retrieve a usable secret after the original create or rotate
    response.

    Attributes:
        id: UUID string identifying the subscription.
        user_id: UUID of the owning user.
        survey_id: Optional survey scope; ``None`` means every survey
            the owner can see.
        target_url: Destination HTTPS URL.
        event_types: Event-type strings the subscription is bound to.
        description: Optional human-readable label.
        active: On/off toggle. ``False`` means the subscription is
            soft-deleted or paused; new events are not dispatched but
            delivery history is retained.
        last_delivery_at: Cached timestamp of the most recent terminal
            delivery; ``None`` until the first delivery completes.
        last_delivery_status: Cached status of the most recent terminal
            delivery (``"succeeded"`` or ``"failed_permanent"``).
        created_at: Insert timestamp.
        updated_at: Last-update timestamp; refreshed on every mutation.
    """

    id: str = Field(
        ...,
        description="UUID identifier for the subscription.",
        examples=["6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8"],
    )
    user_id: str = Field(
        ...,
        description="UUID of the owning user.",
        examples=["a1b2c3d4-e5f6-4789-90ab-cdef01234567"],
    )
    survey_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional survey scope. None means every survey the owner "
            "can see."
        ),
        examples=["d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"],
    )
    target_url: str = Field(
        ...,
        description="Destination HTTPS URL.",
        examples=["https://hooks.example.com/intelligence-survey"],
    )
    event_types: List[str] = Field(
        ...,
        description="Event-type strings the subscription is bound to.",
        examples=[["response.created", "response.completed"]],
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional human-readable label.",
        examples=["Reporting CRM follow-up integration"],
    )
    active: bool = Field(
        ...,
        description=(
            "On/off toggle. False stops new dispatches but retains "
            "delivery history."
        ),
        examples=[True],
    )
    last_delivery_at: Optional[datetime] = Field(
        default=None,
        description="Cached timestamp of the most recent terminal delivery.",
        examples=["2026-09-15T10:23:00Z"],
    )
    last_delivery_status: Optional[str] = Field(
        default=None,
        description=(
            "Cached status of the most recent terminal delivery: "
            "``succeeded`` or ``failed_permanent``."
        ),
        examples=["succeeded"],
    )
    created_at: datetime = Field(
        ...,
        description="Insert timestamp.",
        examples=["2026-09-01T08:00:00Z"],
    )
    updated_at: datetime = Field(
        ...,
        description="Last-update timestamp.",
        examples=["2026-09-15T10:23:00Z"],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8",
                    "user_id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "target_url": (
                        "https://hooks.example.com/intelligence-survey"
                    ),
                    "event_types": [
                        "response.created",
                        "response.completed",
                    ],
                    "description": "Reporting CRM follow-up integration",
                    "active": True,
                    "last_delivery_at": "2026-09-15T10:23:00Z",
                    "last_delivery_status": "succeeded",
                    "created_at": "2026-09-01T08:00:00Z",
                    "updated_at": "2026-09-15T10:23:00Z",
                }
            ]
        },
    )


class WebhookSubscriptionCreateOut(WebhookSubscriptionOut):
    """Response body for ``POST /api/v1/webhooks``.

    Extends :class:`WebhookSubscriptionOut` with the
    ``signing_secret`` field, which is returned exactly once at
    creation time. Callers must capture the value here; it cannot be
    recovered through any subsequent endpoint.

    Attributes:
        signing_secret: Full plaintext signing secret, returned exactly
            once at creation time. Receivers use it to verify the
            ``X-Webhook-Signature`` header on inbound deliveries.
    """

    signing_secret: str = Field(
        ...,
        description=(
            "Full plaintext signing secret, returned exactly once at "
            "creation time. Use it to verify the X-Webhook-Signature "
            "header on inbound deliveries."
        ),
        examples=["whsec_abCD3fGhIjKlMnOpQrStUvWxYzABCDef"],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8",
                    "user_id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "target_url": (
                        "https://hooks.example.com/intelligence-survey"
                    ),
                    "event_types": [
                        "response.created",
                        "response.completed",
                    ],
                    "description": "Reporting CRM follow-up integration",
                    "active": True,
                    "last_delivery_at": None,
                    "last_delivery_status": None,
                    "created_at": "2026-09-01T08:00:00Z",
                    "updated_at": "2026-09-01T08:00:00Z",
                    "signing_secret": (
                        "whsec_abCD3fGhIjKlMnOpQrStUvWxYzABCDef"
                    ),
                }
            ]
        },
    )


class WebhookSubscriptionRotateOut(WebhookSubscriptionOut):
    """Response body for ``POST /api/v1/webhooks/{sub_id}/rotate-secret``.

    Identical shape to :class:`WebhookSubscriptionCreateOut`: the
    rotated subscription carries a fresh ``signing_secret`` while
    ``id`` and target metadata remain stable. The previous secret's
    hash is moved to ``previous_secret_hash`` server-side during the
    rotation invalidation window per Req 3 AC5; that column is never
    exposed to clients.

    Attributes:
        signing_secret: New plaintext signing secret, returned exactly
            once. The previous secret remains accepted for receiver
            verification until the background invalidation task
            clears it.
    """

    signing_secret: str = Field(
        ...,
        description=(
            "New plaintext signing secret, returned exactly once. The "
            "previous secret remains accepted for receiver verification "
            "until the background invalidation task clears it."
        ),
        examples=["whsec_zyXW9vUtSrQpOnMlKjIhGfEdCbA98765"],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8",
                    "user_id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "target_url": (
                        "https://hooks.example.com/intelligence-survey"
                    ),
                    "event_types": [
                        "response.created",
                        "response.completed",
                    ],
                    "description": "Reporting CRM follow-up integration",
                    "active": True,
                    "last_delivery_at": "2026-09-15T10:23:00Z",
                    "last_delivery_status": "succeeded",
                    "created_at": "2026-09-01T08:00:00Z",
                    "updated_at": "2026-09-20T14:00:00Z",
                    "signing_secret": (
                        "whsec_zyXW9vUtSrQpOnMlKjIhGfEdCbA98765"
                    ),
                }
            ]
        },
    )


class WebhookDeliveryOut(BaseModel):
    """Public-facing webhook delivery projection.

    Used by both the per-subscription delivery history endpoint and
    the manual redelivery response. The full ``payload`` is included
    so callers can inspect or replay event content without a separate
    fetch; the field is sourced from the ``WebhookDelivery.payload``
    JSONB column which preserves the original byte-equivalent JSON
    object across retries and manual redelivery (Req 4 AC10).

    Attributes:
        id: UUID string identifying the delivery; this is the same
            value sent to the receiver as ``X-Webhook-Delivery``.
        subscription_id: UUID of the parent subscription.
        event_type: Event-type label, e.g. ``"response.created"``.
        payload: JSON object actually sent or to be sent to the
            receiver.
        status: Current state, one of ``"pending"`` / ``"retrying"`` /
            ``"succeeded"`` / ``"failed_permanent"``.
        attempt_count: Number of HTTP attempts performed.
        last_attempt_at: Timestamp of the most recent attempt, or
            ``None`` before the first attempt.
        last_response_status: HTTP status code from the most recent
            attempt, or ``None`` on network error or before the first
            attempt.
        last_error: Truncated (1000 chars) error message from the most
            recent failed attempt; ``None`` on success.
        next_attempt_at: Scheduled time of the next retry; non-null
            only while ``status == "retrying"``.
        created_at: Insert timestamp; the moment fan-out decided to
            deliver this event.
        completed_at: Timestamp of terminal transition; ``None`` while
            non-terminal.
    """

    id: str = Field(
        ...,
        description="UUID identifying the delivery (also X-Webhook-Delivery).",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    subscription_id: str = Field(
        ...,
        description="UUID of the parent subscription.",
        examples=["6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8"],
    )
    event_type: str = Field(
        ...,
        description="Event-type label, e.g. response.created.",
        examples=["response.created"],
    )
    payload: Dict[str, Any] = Field(
        ...,
        description="JSON object sent (or to be sent) to the receiver.",
        examples=[
            {
                "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                "response_id": "0a1b2c3d-4e5f-6789-abcd-ef0123456789",
                "submitted_at": "2026-09-15T10:22:55Z",
            }
        ],
    )
    status: str = Field(
        ...,
        description=(
            "Delivery state: pending / retrying / succeeded / "
            "failed_permanent."
        ),
        examples=["succeeded"],
    )
    attempt_count: int = Field(
        ...,
        description="Number of HTTP attempts performed.",
        examples=[1],
    )
    last_attempt_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the most recent attempt.",
        examples=["2026-09-15T10:23:00Z"],
    )
    last_response_status: Optional[int] = Field(
        default=None,
        description="HTTP status code from the most recent attempt.",
        examples=[200],
    )
    last_error: Optional[str] = Field(
        default=None,
        description="Truncated error message from the most recent failure.",
        examples=[None],
    )
    next_attempt_at: Optional[datetime] = Field(
        default=None,
        description=(
            "Scheduled time of the next retry; non-null only while "
            "status is retrying."
        ),
        examples=[None],
    )
    created_at: datetime = Field(
        ...,
        description="Insert timestamp.",
        examples=["2026-09-15T10:22:55Z"],
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of terminal transition.",
        examples=["2026-09-15T10:23:00Z"],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "subscription_id": (
                        "6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8"
                    ),
                    "event_type": "response.created",
                    "payload": {
                        "survey_id": (
                            "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"
                        ),
                        "response_id": (
                            "0a1b2c3d-4e5f-6789-abcd-ef0123456789"
                        ),
                        "submitted_at": "2026-09-15T10:22:55Z",
                    },
                    "status": "succeeded",
                    "attempt_count": 1,
                    "last_attempt_at": "2026-09-15T10:23:00Z",
                    "last_response_status": 200,
                    "last_error": None,
                    "next_attempt_at": None,
                    "created_at": "2026-09-15T10:22:55Z",
                    "completed_at": "2026-09-15T10:23:00Z",
                }
            ]
        },
    )

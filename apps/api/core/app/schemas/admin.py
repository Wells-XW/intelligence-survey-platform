"""Pydantic v2 schemas for the platform-admin endpoints.

These schemas project the admin-facing inventories described in
design §Component 11 and Requirements 9.1 through 9.4. Each shape is
deliberately decoupled from the underlying ORM class (``ApiKey``,
``WebhookSubscription``, ``ExportJob``, ``AuditLog``) so the admin
projection can carry cross-tenant fields the owner-facing schemas
intentionally omit (the ``owner_user_id`` of the resource and any
trailing-30-day metric attached to it).

Plaintext-shown-once contract:
    None of the admin shapes carry plaintext credentials or stored
    hashes. Even an admin reviewing the global API-key inventory
    cannot retrieve a usable secret; the create / rotate response on
    ``app/api/v1/api_keys.py`` remains the only place a plaintext
    surfaces, and only to the key's owner. This preserves the
    schema-level enforcement of Requirement 2.3 across the
    administrative surface.

OpenAPI examples:
    Every schema attaches at least one realistic example payload via
    ``ConfigDict(json_schema_extra={"examples": [...]})`` so the
    auto-generated FastAPI documentation pages render concrete
    response bodies for the admin routes (Property 24,
    Requirement 1.4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AdminApiKeyOut(BaseModel):
    """Cross-tenant projection of an :class:`ApiKey` row for admin review.

    Mirrors the owner-facing list shape (no plaintext, no hash, no
    ``inactive`` flag) and adds two admin-only fields drawn from
    Requirement 9.1: the ``owner_user_id`` of the key and a
    ``request_count_30d`` derived at query time from Redis day-window
    counters. The 30-day count is the sum of the per-day counters that
    the rate-limit middleware writes; counters are stored under
    ``ratelimit:{key_prefix}:d:{epoch_day_start}`` with a TTL slightly
    larger than 24 hours, so days that have already aged out of Redis
    appear as missing keys. When *every* day in the trailing 30-day
    window is missing the field is reported as ``None`` to signal that
    no usable telemetry remains rather than ``0`` (which would falsely
    suggest the key has been quiet).

    Attributes:
        id: UUID identifier for the key.
        owner_user_id: UUID of the user who owns the key.
        name: Owner-supplied display label.
        key_prefix: First 11 characters of the plaintext (e.g.
            ``sk_live_ab``); safe to display.
        scopes: Capability labels attached to the key.
        rate_limit_overrides: Optional partial per-window quota
            overrides recorded on the key row.
        expires_at: Optional bounded expiration; ``None`` means no
            time-based expiry.
        last_used_at: Optional timestamp of the most recent successful
            authenticated request.
        revoked_at: Revocation timestamp; ``None`` means the key is
            non-revoked. Per Req 9.1 the inventory is restricted to
            non-revoked keys, so the field is included for parity but
            is expected to be ``None`` in standard responses.
        created_at: Insert timestamp.
        request_count_30d: Sum of Redis day-window counters across the
            trailing 30 days, or ``None`` when no day-window counters
            are still present in Redis (counters are TTL-bounded).
    """

    id: str = Field(
        ...,
        description="UUID identifier for the API key.",
        examples=["d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"],
    )
    owner_user_id: str = Field(
        ...,
        description="UUID of the user who owns the key.",
        examples=["a1b2c3d4-e5f6-4789-90ab-cdef01234567"],
    )
    name: str = Field(
        ...,
        description="Owner-supplied display label.",
        examples=["Reporting CRM integration"],
    )
    key_prefix: str = Field(
        ...,
        description="First 11 characters of the plaintext secret.",
        examples=["sk_live_ab"],
    )
    scopes: List[str] = Field(
        ...,
        description="Capability labels attached to the key.",
        examples=[["survey:read", "response:read"]],
    )
    rate_limit_overrides: Optional[Dict[str, int]] = Field(
        default=None,
        description="Optional partial per-window quota overrides.",
        examples=[{"minute": 120}],
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Optional bounded expiration.",
        examples=["2027-01-01T00:00:00Z"],
    )
    last_used_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the most recent authenticated request.",
        examples=["2026-09-15T10:23:00Z"],
    )
    revoked_at: Optional[datetime] = Field(
        default=None,
        description=(
            "Revocation timestamp. Expected to be null in the inventory "
            "list per Req 9.1; populated on the admin-revoke response."
        ),
        examples=[None],
    )
    created_at: datetime = Field(
        ...,
        description="Insert timestamp.",
        examples=["2026-09-01T08:00:00Z"],
    )
    request_count_30d: Optional[int] = Field(
        default=None,
        description=(
            "Sum of Redis day-window counters across the trailing 30 "
            "days. Null when no day-window counters remain in Redis "
            "(counters are TTL-bounded and expire roughly 24 hours "
            "after each window closes)."
        ),
        examples=[12450],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "owner_user_id": (
                        "a1b2c3d4-e5f6-4789-90ab-cdef01234567"
                    ),
                    "name": "Reporting CRM integration",
                    "key_prefix": "sk_live_ab",
                    "scopes": ["survey:read", "response:read"],
                    "rate_limit_overrides": {"minute": 120},
                    "expires_at": "2027-01-01T00:00:00Z",
                    "last_used_at": "2026-09-15T10:23:00Z",
                    "revoked_at": None,
                    "created_at": "2026-09-01T08:00:00Z",
                    "request_count_30d": 12450,
                }
            ]
        },
    )


class AdminWebhookSubscriptionOut(BaseModel):
    """Cross-tenant projection of a :class:`WebhookSubscription` row.

    Mirrors the owner-facing list shape and adds the admin-only fields
    drawn from Requirement 9.2: the ``owner_user_id`` of the
    subscription and the ``failure_count_30d`` of permanently failed
    deliveries observed in the trailing 30-day window. The failure
    count is a count of ``WebhookDelivery`` rows whose ``status`` is
    ``failed_permanent`` and whose ``created_at`` falls within the
    window; it is always a non-negative integer (zero when the
    subscription has had no permanent failures in the window).

    Per Req 9.2 the admin inventory is restricted to *active*
    subscriptions; the ``active`` field is included for shape parity
    with the owner-facing schema and is expected to be ``True`` in
    standard responses.

    Attributes:
        id: UUID identifier for the subscription.
        owner_user_id: UUID of the user who owns the subscription.
        survey_id: Optional survey scope; ``None`` matches every
            survey the owner can see.
        target_url: Destination HTTPS URL.
        event_types: Event-type strings the subscription is bound to.
        description: Optional human-readable label.
        active: On/off toggle. Expected to be ``True`` per Req 9.2.
        last_delivery_at: Cached timestamp of the most recent terminal
            delivery; ``None`` until the first delivery completes.
        last_delivery_status: Cached status of the most recent
            terminal delivery (``"succeeded"`` or
            ``"failed_permanent"``).
        created_at: Insert timestamp.
        updated_at: Last-update timestamp.
        failure_count_30d: Count of ``WebhookDelivery`` rows for this
            subscription with ``status='failed_permanent'`` and
            ``created_at`` within the trailing 30 days.
    """

    id: str = Field(
        ...,
        description="UUID identifier for the subscription.",
        examples=["6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8"],
    )
    owner_user_id: str = Field(
        ...,
        description="UUID of the user who owns the subscription.",
        examples=["a1b2c3d4-e5f6-4789-90ab-cdef01234567"],
    )
    survey_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional survey scope. None means every survey the "
            "owner can see."
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
            "On/off toggle. Expected to be True in the inventory list "
            "per Req 9.2."
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
    failure_count_30d: int = Field(
        ...,
        ge=0,
        description=(
            "Count of WebhookDelivery rows for this subscription with "
            "status='failed_permanent' whose created_at falls within "
            "the trailing 30 days."
        ),
        examples=[3],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8",
                    "owner_user_id": (
                        "a1b2c3d4-e5f6-4789-90ab-cdef01234567"
                    ),
                    "survey_id": (
                        "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"
                    ),
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
                    "failure_count_30d": 3,
                }
            ]
        },
    )


class AdminExportJobOut(BaseModel):
    """Cross-tenant projection of an :class:`ExportJob` row for admin review.

    Mirrors the owner-facing :class:`ExportJobOut` shape minus the
    ``download_url`` field (admin inventory does not mint download
    tokens — admins requesting a file go through the standard download
    path with their own credentials) and adds the admin-only
    ``owner_user_id`` field per Requirement 9.3.

    Attributes:
        id: UUID identifier for the export job.
        owner_user_id: UUID of the requesting user.
        survey_id: UUID of the source survey.
        format: Output format identifier.
        status: Current state-machine position; one of ``queued`` /
            ``running`` / ``succeeded`` / ``failed`` / ``expired``.
        options: Reserved materialization-options map; currently
            unused.
        byte_size: Size in bytes of the rendered artifact, populated
            only on transition to ``succeeded``.
        error_message: Truncated (1000 chars) failure description,
            populated only on transition to ``failed``.
        created_at: Insert timestamp.
        started_at: Timestamp set when the worker dequeued the row.
        completed_at: Timestamp set when the row reached a terminal
            state.
        expires_at: Retention deadline for the rendered artifact;
            populated only on transition to ``succeeded``.
    """

    id: str = Field(
        ...,
        description="UUID identifier for the export job.",
        examples=["6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8"],
    )
    owner_user_id: str = Field(
        ...,
        description="UUID of the requesting user.",
        examples=["a1b2c3d4-e5f6-4789-90ab-cdef01234567"],
    )
    survey_id: str = Field(
        ...,
        description="UUID of the source survey.",
        examples=["d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"],
    )
    format: str = Field(
        ...,
        description="Output format identifier.",
        examples=["csv"],
    )
    status: str = Field(
        ...,
        description=(
            "Current state: queued / running / succeeded / failed / "
            "expired."
        ),
        examples=["succeeded"],
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Reserved materialization-options map; currently unused.",
        examples=[None],
    )
    byte_size: Optional[int] = Field(
        default=None,
        description=(
            "Size in bytes of the rendered artifact; non-null only on "
            "succeeded."
        ),
        examples=[12345],
    )
    error_message: Optional[str] = Field(
        default=None,
        description=(
            "Truncated failure description; non-null only on failed."
        ),
        examples=[None],
    )
    created_at: datetime = Field(
        ...,
        description="Insert timestamp.",
        examples=["2026-09-15T10:22:55Z"],
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp the worker began materialization.",
        examples=["2026-09-15T10:23:00Z"],
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of terminal transition.",
        examples=["2026-09-15T10:23:05Z"],
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description=(
            "Retention deadline for the rendered artifact; non-null "
            "only on succeeded."
        ),
        examples=["2026-09-22T10:23:05Z"],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8",
                    "owner_user_id": (
                        "a1b2c3d4-e5f6-4789-90ab-cdef01234567"
                    ),
                    "survey_id": (
                        "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"
                    ),
                    "format": "csv",
                    "status": "succeeded",
                    "options": None,
                    "byte_size": 12345,
                    "error_message": None,
                    "created_at": "2026-09-15T10:22:55Z",
                    "started_at": "2026-09-15T10:23:00Z",
                    "completed_at": "2026-09-15T10:23:05Z",
                    "expires_at": "2026-09-22T10:23:05Z",
                }
            ]
        },
    )


class AdminAuditLogOut(BaseModel):
    """Read projection of an :class:`AuditLog` row for the admin query API.

    Surfaces every field the existing append-only audit table records.
    The schema is intentionally a flat shape — ``details`` is exposed
    as an opaque JSON object so admins can consume the per-verb extras
    (key names, target URLs, attempt counts, formats, byte sizes,
    rate-limit windows, ...) without the schema layer having to grow
    a discriminator on every new audit verb.

    Attributes:
        id: Bigint primary key from ``audit_logs.id``.
        user_id: UUID of the actor user, or ``None`` for system or
            anonymous events.
        action: Canonical action verb (e.g.
            ``"api_key.admin_revoke"``).
        resource_type: Resource type label (e.g. ``"api_key"``,
            ``"webhook_subscription"``, ``"export_job"``,
            ``"system"``); ``None`` when not applicable.
        resource_id: Resource identifier scoped by ``resource_type``;
            ``None`` when not applicable.
        details: Verb-specific JSON object; shape depends on the
            ``action`` verb.
        ip_address: Client IP captured at log time, or ``None``.
        user_agent: Client user-agent string, or ``None``.
        created_at: Audit insert timestamp.
    """

    id: int = Field(
        ...,
        description="Bigint primary key from audit_logs.id.",
        examples=[1024],
    )
    user_id: Optional[str] = Field(
        default=None,
        description=(
            "UUID of the actor user, or null for system or anonymous "
            "events."
        ),
        examples=["a1b2c3d4-e5f6-4789-90ab-cdef01234567"],
    )
    action: str = Field(
        ...,
        description="Canonical action verb.",
        examples=["api_key.admin_revoke"],
    )
    resource_type: Optional[str] = Field(
        default=None,
        description="Resource type label; null when not applicable.",
        examples=["api_key"],
    )
    resource_id: Optional[str] = Field(
        default=None,
        description=(
            "Resource identifier scoped by resource_type; null when "
            "not applicable."
        ),
        examples=["d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"],
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Verb-specific JSON object; shape depends on the action "
            "verb."
        ),
        examples=[
            {
                "key_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                "name": "Reporting CRM integration",
                "owner_user_id": (
                    "a1b2c3d4-e5f6-4789-90ab-cdef01234567"
                ),
                "admin_user_id": (
                    "9f8e7d6c-5b4a-3210-fedc-ba9876543210"
                ),
            }
        ],
    )
    ip_address: Optional[str] = Field(
        default=None,
        description="Client IP captured at log time, or null.",
        examples=["198.51.100.7"],
    )
    user_agent: Optional[str] = Field(
        default=None,
        description="Client user-agent string, or null.",
        examples=["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"],
    )
    created_at: datetime = Field(
        ...,
        description="Audit insert timestamp.",
        examples=["2026-09-20T14:00:00Z"],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 1024,
                    "user_id": (
                        "9f8e7d6c-5b4a-3210-fedc-ba9876543210"
                    ),
                    "action": "api_key.admin_revoke",
                    "resource_type": "api_key",
                    "resource_id": (
                        "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"
                    ),
                    "details": {
                        "key_id": (
                            "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"
                        ),
                        "name": "Reporting CRM integration",
                        "owner_user_id": (
                            "a1b2c3d4-e5f6-4789-90ab-cdef01234567"
                        ),
                        "admin_user_id": (
                            "9f8e7d6c-5b4a-3210-fedc-ba9876543210"
                        ),
                    },
                    "ip_address": "198.51.100.7",
                    "user_agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
                    ),
                    "created_at": "2026-09-20T14:00:00Z",
                }
            ]
        },
    )

"""Pydantic v2 schemas for the API key lifecycle endpoints.

These schemas define the request and response shapes for the routes in
``app/api/v1/api_keys.py``. They are deliberately decoupled from the
:class:`app.models.api_key.ApiKey` ORM class so that documentation and
serialization can evolve independently of the database layer.

Plaintext-shown-once contract:
    The full secret value (``plaintext``) is exposed only on the
    create-response shape (``ApiKeyCreateOut``) and the rotate-response
    shape (``ApiKeyRotateOut``). The list / detail shape
    (``ApiKeyOut``) intentionally omits both the plaintext secret and
    its stored hash so callers cannot retrieve a key after the moment
    it was issued. This shape boundary is the schema-level enforcement
    of Requirement 2.3 (plaintext exposure is exactly-once).

OpenAPI examples:
    Every schema attaches at least one realistic example payload via
    ``ConfigDict(json_schema_extra={"examples": [...]})`` so the
    auto-generated FastAPI documentation pages render concrete request
    and response bodies (Property 24, Requirement 1.4).
"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateIn(BaseModel):
    """Request body for ``POST /api/v1/api-keys``.

    Attributes:
        name: Human-readable label for the new key. Maximum length is
            120 characters to match the ORM column.
        scopes: Non-empty list of capability labels drawn from the
            fixed scope enum validated server-side in the route layer.
        expires_at: Optional bounded expiration timestamp; ``None``
            means the key has no time-based expiry.
        rate_limit_overrides: Optional partial override map with keys
            from ``{"minute", "hour", "day"}``; any window not present
            falls back to the platform default quota.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Human-readable label for the API key.",
        examples=["Reporting CRM integration"],
    )
    scopes: List[str] = Field(
        ...,
        min_length=1,
        description=(
            "Non-empty list of scope labels drawn from the fixed enum "
            "(e.g. ``survey:read``, ``response:read``)."
        ),
        examples=[["survey:read", "response:read"]],
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Optional bounded expiration. None means no expiry.",
        examples=["2027-01-01T00:00:00Z"],
    )
    rate_limit_overrides: Optional[Dict[str, int]] = Field(
        default=None,
        description=(
            "Optional partial override map for per-window quotas. "
            "Keys are ``minute``, ``hour``, ``day``."
        ),
        examples=[{"minute": 120, "hour": 2400}],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Reporting CRM integration",
                    "scopes": ["survey:read", "response:read"],
                    "expires_at": "2027-01-01T00:00:00Z",
                    "rate_limit_overrides": {"minute": 120, "hour": 2400},
                }
            ]
        }
    )


class ApiKeyOut(BaseModel):
    """Public-facing API key projection used by list and detail views.

    Excludes the plaintext secret and the stored hash so a caller can
    never retrieve a usable credential after the original create or
    rotate response. The ``inactive`` flag is computed by the route
    handler against the configured inactivity threshold.

    Attributes:
        id: UUID string identifying the key.
        name: Owner-supplied display label.
        key_prefix: First 11 characters of the plaintext (e.g.
            ``sk_live_ab``); safe to display.
        scopes: Capability labels the key may exercise.
        rate_limit_overrides: Optional per-window quota overrides.
        expires_at: Optional bounded expiration; ``None`` means no
            time-based expiry.
        last_used_at: Optional timestamp of the most recent successful
            authenticated request; ``None`` if the key has never been
            used.
        revoked_at: Optional revocation timestamp; non-``None`` marks
            the key as permanently inert.
        created_at: Insert timestamp.
        inactive: Computed by the caller; ``True`` when the time since
            ``last_used_at`` (or ``created_at`` if never used) exceeds
            the configured inactivity threshold.
    """

    id: str = Field(
        ...,
        description="UUID identifier for the key.",
        examples=["d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"],
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
        description="Revocation timestamp; non-null marks the key inert.",
        examples=[None],
    )
    created_at: datetime = Field(
        ...,
        description="Insert timestamp.",
        examples=["2026-09-01T08:00:00Z"],
    )
    inactive: bool = Field(
        ...,
        description=(
            "Computed flag: True when time since last_used_at "
            "(or created_at if never used) exceeds the configured "
            "inactivity threshold."
        ),
        examples=[False],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "name": "Reporting CRM integration",
                    "key_prefix": "sk_live_ab",
                    "scopes": ["survey:read", "response:read"],
                    "rate_limit_overrides": {"minute": 120},
                    "expires_at": "2027-01-01T00:00:00Z",
                    "last_used_at": "2026-09-15T10:23:00Z",
                    "revoked_at": None,
                    "created_at": "2026-09-01T08:00:00Z",
                    "inactive": False,
                }
            ]
        },
    )


class ApiKeyCreateOut(ApiKeyOut):
    """Response body for ``POST /api/v1/api-keys``.

    Extends :class:`ApiKeyOut` with the ``plaintext`` field, which is
    returned exactly once at creation time. Callers must capture the
    value here; it cannot be recovered through any subsequent
    endpoint.

    Attributes:
        plaintext: Full secret in the form
            ``sk_<env>_<24 url-safe characters>``. Shown once.
    """

    plaintext: str = Field(
        ...,
        description=(
            "Full secret value, returned exactly once at creation time. "
            "Format: ``sk_<env>_<24 url-safe characters>``."
        ),
        examples=["sk_live_EXAMPLE-PLACEHOLDER-do-not-use_001"],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "name": "Reporting CRM integration",
                    "key_prefix": "sk_live_ab",
                    "scopes": ["survey:read", "response:read"],
                    "rate_limit_overrides": {"minute": 120},
                    "expires_at": "2027-01-01T00:00:00Z",
                    "last_used_at": None,
                    "revoked_at": None,
                    "created_at": "2026-09-01T08:00:00Z",
                    "inactive": False,
                    "plaintext": "sk_live_EXAMPLE-PLACEHOLDER-do-not-use_001",
                }
            ]
        },
    )


class ApiKeyRotateOut(ApiKeyOut):
    """Response body for ``POST /api/v1/api-keys/{key_id}/rotate``.

    Identical shape to :class:`ApiKeyCreateOut`: the rotated key
    carries a fresh ``plaintext`` value and a fresh ``key_prefix``,
    while ``id`` remains stable so the row identity survives rotation.

    Attributes:
        plaintext: New secret value, returned exactly once. The
            previous secret is invalidated immediately upon rotation.
    """

    plaintext: str = Field(
        ...,
        description=(
            "New secret value, returned exactly once. The previous "
            "secret is invalidated immediately upon rotation."
        ),
        examples=["sk_live_EXAMPLE-PLACEHOLDER-do-not-use_002"],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "name": "Reporting CRM integration",
                    "key_prefix": "sk_live_zy",
                    "scopes": ["survey:read", "response:read"],
                    "rate_limit_overrides": {"minute": 120},
                    "expires_at": "2027-01-01T00:00:00Z",
                    "last_used_at": "2026-09-15T10:23:00Z",
                    "revoked_at": None,
                    "created_at": "2026-09-01T08:00:00Z",
                    "inactive": False,
                    "plaintext": "sk_live_EXAMPLE-PLACEHOLDER-do-not-use_002",
                }
            ]
        },
    )

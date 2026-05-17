"""Pydantic v2 schemas for the export job endpoints.

These schemas define the request and response shapes for the routes in
``app/api/v1/exports.py``. They are deliberately decoupled from the
:class:`app.models.export_job.ExportJob` ORM class so that documentation
and serialization can evolve independently of the database layer.

Computed-field contract:
    The ``download_url`` field on :class:`ExportJobOut` is set by the
    route handler — never by the ORM — and only when the job's status
    is ``"succeeded"``. The handler mints a fresh signed download
    token via :func:`app.core.export_download_token.issue` and embeds
    it as a query parameter on the download path. For every other
    status the field is ``None``. This matches Req 5.10's "if and only
    if the status is ``succeeded``" wording exactly.

OpenAPI examples:
    Every schema attaches at least one realistic example payload via
    ``ConfigDict(json_schema_extra={"examples": [...]})`` so the
    auto-generated FastAPI documentation pages render concrete request
    and response bodies (Req 1.4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExportJobCreateIn(BaseModel):
    """Request body for ``POST /api/v1/exports``.

    Attributes:
        survey_id: UUID of the survey whose responses will be
            materialized. The caller must hold at least viewer
            permission on this survey or the route returns 404 to
            hide existence.
        format: Output format identifier. Must be a member of
            ``SUPPORTED_FORMATS`` at runtime; otherwise the route
            returns 400 ``export_format_unsupported``. The mandatory
            members are ``"csv"``, ``"xlsx"``, and ``"json"``;
            ``"sav"`` and ``"xpt"`` are accepted only when the
            optional ``pyreadstat`` dependency is importable on the
            worker host. The SAS path is XPORT (``.xpt``) rather than
            ``.sas7bdat`` because pyreadstat ships only a SAS7BDAT
            reader; downstream SAS users import via ``PROC CIMPORT``.
        options: Reserved JSONB map for future materialization knobs
            (date range filters, column subsets, locale overrides).
            Currently unused; the worker ignores any contents.
    """

    survey_id: str = Field(
        ...,
        min_length=1,
        description=(
            "UUID of the survey whose responses will be materialized."
        ),
        examples=["d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"],
    )
    format: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description=(
            "Output format identifier. One of csv, xlsx, json (always "
            "available); sav, xpt (when pyreadstat is installed). "
            "The xpt format is SAS Transport (import via PROC CIMPORT)."
        ),
        examples=["csv"],
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Reserved JSONB map for future materialization knobs. "
            "Currently unused by the worker."
        ),
        examples=[None],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "format": "csv",
                    "options": None,
                }
            ]
        }
    )


class ExportJobOut(BaseModel):
    """Public-facing export job projection.

    Used by both the create-response and the status-detail endpoints.
    The ``download_url`` field is populated only when ``status`` is
    ``"succeeded"``; for every other status it is ``None``. The URL
    carries a short-lived signed JWT (default 15 minutes) issued by
    :func:`app.core.export_download_token.issue`; callers who need a
    fresh URL after expiry should re-fetch ``GET /{job_id}``.

    Attributes:
        id: UUID identifying the job.
        user_id: UUID of the requesting user.
        survey_id: UUID of the source survey.
        format: Output format identifier; one of ``csv`` / ``xlsx`` /
            ``json`` / ``sav`` / ``xpt``.
        status: Current state-machine position; one of ``queued`` /
            ``running`` / ``succeeded`` / ``failed`` / ``expired``.
        options: Reserved materialization-options map; currently
            unused.
        byte_size: Size in bytes of the rendered artifact, populated
            only on transition to ``succeeded``.
        error_message: Truncated (1000 chars) failure description,
            populated only on transition to ``failed``.
        created_at: Insert timestamp.
        started_at: Timestamp set when the worker dequeues the row
            and transitions it to ``running``.
        completed_at: Timestamp set when the row reaches a terminal
            state (``succeeded`` / ``failed``).
        expires_at: Retention deadline for the rendered artifact;
            populated only on transition to ``succeeded``.
        download_url: Time-limited URL to fetch the rendered file;
            non-null only when ``status == "succeeded"``.
    """

    id: str = Field(
        ...,
        description="UUID identifier for the export job.",
        examples=["6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8"],
    )
    user_id: str = Field(
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
    download_url: Optional[str] = Field(
        default=None,
        description=(
            "Time-limited URL to fetch the rendered file. Non-null "
            "only when status is succeeded; carries a signed token "
            "valid for ~15 minutes. Re-fetch GET /{job_id} for a "
            "fresh URL after expiry."
        ),
        examples=[
            "/api/v1/exports/6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8/download"
            "?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
        ],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8",
                    "user_id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "format": "csv",
                    "status": "succeeded",
                    "options": None,
                    "byte_size": 12345,
                    "error_message": None,
                    "created_at": "2026-09-15T10:22:55Z",
                    "started_at": "2026-09-15T10:23:00Z",
                    "completed_at": "2026-09-15T10:23:05Z",
                    "expires_at": "2026-09-22T10:23:05Z",
                    "download_url": (
                        "/api/v1/exports/"
                        "6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8/download"
                        "?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                    ),
                }
            ]
        },
    )


class ExportJobListItem(ExportJobOut):
    """List-response projection.

    Identical shape to :class:`ExportJobOut`; declared as a separate
    name so the OpenAPI schema documents the list endpoint's element
    type explicitly. The list endpoint omits ``download_url`` (sets
    it to ``None``) for every item to avoid issuing dozens of
    short-lived signed tokens on a single page load — the caller
    fetches ``GET /{job_id}`` to obtain a fresh URL on demand.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "6c2a4d2c-8a11-4f3b-9f1e-d3b07384d9a8",
                    "user_id": "a1b2c3d4-e5f6-4789-90ab-cdef01234567",
                    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
                    "format": "csv",
                    "status": "succeeded",
                    "options": None,
                    "byte_size": 12345,
                    "error_message": None,
                    "created_at": "2026-09-15T10:22:55Z",
                    "started_at": "2026-09-15T10:23:00Z",
                    "completed_at": "2026-09-15T10:23:05Z",
                    "expires_at": "2026-09-22T10:23:05Z",
                    "download_url": None,
                }
            ]
        },
    )

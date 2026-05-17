"""Export job lifecycle and download routes for the survey-data export pipeline.

These endpoints implement Components 6 and 8 of the design: ``POST /``,
``GET /{job_id}``, ``GET /{job_id}/download``, and ``GET /``. They satisfy
Requirements 5.1, 5.2, 5.3, 5.10, and 5.11.

Format admission:
    The ``POST /`` route consults
    :data:`app.services.export_formats.SUPPORTED_FORMATS` on every request
    rather than caching the value at module-import time. That set is
    initialized to ``{"csv", "xlsx", "json"}`` at process start and is
    extended with ``{"sav", "sas7bdat"}`` only when ``pyreadstat`` is
    importable in the worker's runtime environment per design §Component 7.
    Reading it on demand keeps the route honest about format availability
    on a per-host basis.

Owner-scoped reads:
    The status, list, and download routes hide existence of jobs owned
    by another user with a 404 (rather than 403). This mirrors the
    "hide-existence" pattern the rest of the platform uses for
    survey-scoped resources: a caller without ownership cannot enumerate
    or probe the existence of jobs they do not own.

Hybrid authentication on download:
    The download endpoint accepts three authentication paths per Req 5
    AC11:
    * a signed download token in the ``token`` query parameter (used by
      browsers, email clients, and other non-API-aware tools); the token
      must carry ``purpose == "export_download"``, ``jti == job_id``,
      and an ``exp`` claim in the future;
    * a JWT bearer credential (carries the wildcard scope ``"*"``); or
    * an API key whose stored scopes include ``export:read`` (or the
      wildcard ``"*"``).
    The token path takes precedence: when ``token`` is supplied, the
    endpoint never falls through to ``get_principal``. This ensures a
    leaked download token cannot be silently upgraded to broader
    credentials by appending an unrelated header.

The route layer never inspects ``ExportJob.storage_path`` for any
purpose other than serving an authenticated download. Path values are
written exclusively by the export worker
(:mod:`app.tasks.export_tasks`) and are treated as opaque by the API
layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import export_download_token
from ...core.audit import log_audit
from ...core.deps import (
    Principal,
    check_survey_permission,
    get_principal,
)
from ...database import get_db
from ...models.export_job import ExportJob
from ...schemas.export import (
    ExportJobCreateIn,
    ExportJobListItem,
    ExportJobOut,
)
from ...services.export_formats import SUPPORTED_FORMATS

router = APIRouter(prefix="/exports", tags=["exports"])


# ── Module constants ──────────────────────────────────────────────────

#: Outbound media types per export format. The values follow the
#: standards each format ships under: CSV declares ``charset=utf-8`` so
#: receivers honour the BOM the producer emits, XLSX uses the modern
#: OOXML MIME type rather than the legacy ``application/vnd.ms-excel``,
#: and the SPSS / SAS binary formats fall back to
#: ``application/octet-stream`` because IANA has no registered MIME for
#: either. ``application/octet-stream`` is also the safe default for any
#: future format that lands here without a dedicated row.
_MEDIA_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    "json": "application/json",
    "sav": "application/octet-stream",
    "sas7bdat": "application/octet-stream",
}

#: Default page size for the list endpoint. Matches the per-feature
#: convention chosen for webhook delivery history so admin UIs can
#: assume a uniform default across this feature's list endpoints.
_DEFAULT_LIST_LIMIT: int = 50

#: Hard upper bound on the per-page job count. Caller-supplied
#: ``limit`` values higher than this are rejected by FastAPI's query
#: validation rather than silently clamped — the list endpoint is
#: paginated, and a too-large page is a client bug worth surfacing.
_MAX_LIST_LIMIT: int = 200


# ── Helpers ───────────────────────────────────────────────────────────


def _build_job_payload(row: ExportJob) -> dict:
    """Serialize an :class:`ExportJob` row into the shared output shape.

    The shape matches both :class:`ExportJobOut` and
    :class:`ExportJobListItem`. Callers that need a populated
    ``download_url`` attach it after calling this helper; this helper
    always sets the field to ``None`` so the default is the safe one
    (no leaked URL on non-succeeded jobs).

    Args:
        row: The :class:`ExportJob` row to serialize.

    Returns:
        A dict suitable for ``ExportJobOut(**payload)`` or
        ``ExportJobListItem(**payload)``.
    """
    return {
        "id": row.id,
        "user_id": row.user_id,
        "survey_id": row.survey_id,
        "format": row.format,
        "status": row.status,
        "options": row.options,
        "byte_size": row.byte_size,
        "error_message": row.error_message,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "expires_at": row.expires_at,
        "download_url": None,
    }


def _mint_download_url(user_id: str, job_id: str) -> str:
    """Mint a fresh signed download URL for one export job.

    Builds a path of the form ``/api/v1/exports/{job_id}/download?token=<jwt>``.
    The token is issued by :func:`app.core.export_download_token.issue`
    with the default TTL configured in
    :attr:`Settings.export_download_token_ttl_seconds` (15 minutes per
    design §Component 8). Re-fetching ``GET /{job_id}`` after expiry
    yields a fresh URL.

    Args:
        user_id: The owning user's id; placed in the token's ``sub``
            claim.
        job_id: The export job id; placed in the token's ``jti`` claim
            and embedded in the URL path.

    Returns:
        Path-and-query string suitable for return in the
        ``download_url`` field of an :class:`ExportJobOut`.
    """
    token = export_download_token.issue(user_id=user_id, job_id=job_id)
    return f"/api/v1/exports/{job_id}/download?token={token}"


def _enqueue_materialize(job_id: str) -> None:
    """Best-effort enqueue of an export job on the ``exports`` Celery queue.

    The export worker (:mod:`app.tasks.export_tasks`) is the eventual
    consumer. We use :meth:`Celery.send_task` rather than importing
    the worker module directly so that the API process does not depend
    on the worker being importable in its environment; Celery resolves
    the task by name on the broker side.

    Failures are intentionally non-fatal: the row has already been
    persisted in status ``queued`` and an operator (or future
    reconciler) can re-enqueue stuck jobs. Surfacing a transient
    broker outage as a 500 to the caller would be worse than the
    eventual-consistency window an operator can close.

    Args:
        job_id: UUID string of the job row to dispatch.
    """
    try:
        # Imported lazily so a development environment without Celery
        # configured (e.g. a unit test file run in isolation) does not
        # error at module import time.
        from ...tasks import celery_app

        celery_app.send_task(
            "app.tasks.export_tasks.materialize_export",
            args=[job_id],
            queue="exports",
        )
    except Exception:
        # Swallow: the row exists, an operator can re-enqueue. We
        # intentionally do not log here to avoid wiring a logger
        # surface for what is by design a recoverable miss.
        pass


async def _resolve_download_caller(
    request: Request,
    job_id: str,
    token: Optional[str],
    db: AsyncSession,
) -> str:
    """Resolve the caller of ``GET /{job_id}/download`` to a user id.

    Implements the three-path authentication contract described in the
    module docstring. The token path is consulted first and to the
    exclusion of any other credential header — if a ``token`` query
    parameter is present, the endpoint either accepts it or rejects
    the request, never falling through to ``get_principal``. When no
    token is supplied, the endpoint resolves a :class:`Principal` via
    :func:`get_principal` and gates API-key principals on the
    ``export:read`` scope; JWT principals always pass because they
    carry the wildcard scope ``"*"``.

    Args:
        request: The inbound FastAPI request, forwarded to
            :func:`get_principal` for header parsing when no token is
            supplied.
        job_id: The export job id from the URL path; matched against
            the token's ``jti`` claim.
        token: The optional ``token`` query parameter.
        db: Active async database session.

    Returns:
        The ``user_id`` of the authenticated caller.

    Raises:
        HTTPException: 401 ``invalid_download_token`` when a token was
            supplied but failed verification (wrong purpose, ``jti``
            mismatch, expired, or malformed); 401 ``auth_required``
            when no token was supplied and no valid JWT or API key
            could be resolved; 403 ``insufficient_scope`` when an API
            key was resolved but its scopes do not include
            ``export:read``.
    """
    if token is not None:
        user_id = export_download_token.verify(token, job_id)
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_download_token"},
            )
        return user_id

    try:
        principal: Principal = await get_principal(request=request, db=db)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "auth_required"},
        )

    # JWT principals carry the wildcard scope ``"*"``; API-key
    # principals must explicitly hold ``export:read``. The wildcard
    # check is honoured for symmetry with :func:`require_scope`.
    if "*" not in principal.scopes and "export:read" not in principal.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "insufficient_scope",
                "required_scope": "export:read",
            },
        )
    return principal.user.id


# ── Routes ────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=ExportJobOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an export job",
    description=(
        "Create an asynchronous export job for one survey in one of the "
        "runtime-supported formats. The response carries the new job "
        "in status ``queued``; poll ``GET /{job_id}`` to track progress "
        "and obtain a download URL once the job reaches ``succeeded``."
    ),
)
async def create_export_job(
    body: ExportJobCreateIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> ExportJobOut:
    """Create a new export job for the authenticated caller.

    Validates that ``body.format`` is a member of the runtime-supported
    set (Req 5 AC1, AC2, AC3) and that the caller holds at least viewer
    permission on ``body.survey_id`` before any write. Inserts a fresh
    :class:`ExportJob` row in status ``queued`` and emits an
    ``export.job.created`` audit row carrying the job id, survey id,
    and format. Best-effort enqueues the materialization Celery task on
    the ``exports`` queue; broker outages are non-fatal because the
    row is already durable and an operator can re-enqueue.

    Args:
        body: Create payload with ``survey_id``, ``format``, and
            optional ``options``.
        request: Inbound request, used for audit attribution.
        principal: The authenticated caller. Both JWT and API-key
            principals are accepted; API-key principals additionally
            need either the wildcard scope or ``export:write`` per
            the standard scope model — the route layer does not
            enforce ``export:write`` here because the survey-RBAC
            check below already gates write-side activity.
        db: Async database session.

    Returns:
        The :class:`ExportJobOut` payload for the newly created job in
        status ``queued``. ``download_url`` is ``None`` until the job
        succeeds.

    Raises:
        HTTPException: 400 ``export_format_unsupported`` when
            ``body.format`` is not in the runtime-supported set; 404
            via :func:`check_survey_permission` when the caller has no
            view rights on the target survey.
    """
    # Format admission is read on every request so a worker host that
    # gains or loses pyreadstat between requests is reflected
    # immediately. The error body echoes the supported set sorted so
    # callers can drive a corrective UI without a separate lookup.
    if body.format not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "export_format_unsupported",
                "format": body.format,
                "supported": sorted(SUPPORTED_FORMATS),
            },
        )

    # Survey-RBAC gate. ``check_survey_permission`` returns a 404 when
    # the caller has no permission on the target survey, hiding survey
    # existence from unauthorized callers — the same pattern used by
    # every other survey-scoped route in the platform.
    await check_survey_permission(body.survey_id, principal.user, "viewer", db)

    row = ExportJob(
        user_id=principal.user.id,
        survey_id=body.survey_id,
        format=body.format,
        status="queued",
        options=body.options,
    )
    db.add(row)
    await db.flush()

    await log_audit(
        db,
        action="export.job.created",
        user_id=principal.user.id,
        resource_type="export_job",
        resource_id=row.id,
        details={
            "job_id": row.id,
            "survey_id": row.survey_id,
            "format": row.format,
        },
        request=request,
    )

    await db.commit()
    await db.refresh(row)

    # Best-effort enqueue after commit so the worker only sees rows that
    # are durably persisted. A broker outage at this point leaves a
    # ``queued`` row that an operator (or a future reconciler) can pick
    # up; surfacing it as a 500 would be worse than that.
    _enqueue_materialize(row.id)

    return ExportJobOut(**_build_job_payload(row))


@router.get(
    "/",
    response_model=List[ExportJobListItem],
    summary="List the caller's export jobs",
    description=(
        "Return export jobs owned by the authenticated caller, "
        "newest-first. Optionally filter by ``survey_id`` and "
        "``status``. ``download_url`` is omitted on every list item — "
        "fetch ``GET /{job_id}`` to obtain a fresh signed URL on demand."
    ),
)
async def list_export_jobs(
    survey_id: Optional[str] = Query(
        default=None,
        description="Optional survey-id filter.",
    ),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description=(
            "Optional status filter; one of queued / running / "
            "succeeded / failed / expired."
        ),
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> List[ExportJobListItem]:
    """List the authenticated caller's export jobs, paginated.

    Returns rows in ``created_at DESC`` order so the most recent job
    is first. Both in-flight (``queued`` / ``running``) and terminal
    (``succeeded`` / ``failed`` / ``expired``) jobs are included so
    callers can monitor live state alongside historical work. The
    ``download_url`` field is intentionally ``None`` on every list
    item so a single page load does not mint dozens of short-lived
    signed tokens; callers fetch ``GET /{job_id}`` to obtain a fresh
    URL on demand.

    Args:
        survey_id: Optional survey-id filter.
        status_filter: Optional status filter (mapped from the
            ``status`` query param to avoid shadowing the imported
            :mod:`fastapi.status` module).
        offset: Pagination offset; non-negative.
        limit: Page size; clamped to ``[1, 200]`` by FastAPI's query
            validation.
        principal: The authenticated caller.
        db: Async database session.

    Returns:
        A list of :class:`ExportJobListItem` payloads.
    """
    stmt = (
        select(ExportJob)
        .where(ExportJob.user_id == principal.user.id)
        .order_by(ExportJob.created_at.desc())
    )
    if survey_id is not None:
        stmt = stmt.where(ExportJob.survey_id == survey_id)
    if status_filter is not None:
        stmt = stmt.where(ExportJob.status == status_filter)
    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [ExportJobListItem(**_build_job_payload(r)) for r in rows]


@router.get(
    "/{job_id}",
    response_model=ExportJobOut,
    summary="Get an export job's status",
    description=(
        "Return the current state of one export job owned by the "
        "authenticated caller. The ``download_url`` field is "
        "populated only when ``status == \"succeeded\"`` and carries "
        "a signed token valid for ~15 minutes (per "
        "``EXPORT_DOWNLOAD_TOKEN_TTL_SECONDS``)."
    ),
)
async def get_export_job(
    job_id: str,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> ExportJobOut:
    """Return the current state of one export job.

    Loads the row by primary key and verifies the caller owns it; jobs
    owned by another user are reported as 404 to hide existence (Req 5
    AC10). When the job is in status ``succeeded``, mints a fresh
    signed download URL via :func:`_mint_download_url` and embeds it
    in the response. For every other status the field is ``None`` —
    this matches Req 5 AC10's "if and only if" wording exactly.

    Args:
        job_id: The id of the export job from the URL path.
        principal: The authenticated caller.
        db: Async database session.

    Returns:
        The :class:`ExportJobOut` payload.

    Raises:
        HTTPException: 404 ``export_job_not_found`` when the job is
            unknown or owned by a different user.
    """
    row = await db.get(ExportJob, job_id)
    if row is None or row.user_id != principal.user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "export_job_not_found"},
        )

    payload = _build_job_payload(row)
    if row.status == "succeeded":
        payload["download_url"] = _mint_download_url(
            user_id=principal.user.id, job_id=row.id
        )
    return ExportJobOut(**payload)


@router.get(
    "/{job_id}/download",
    summary="Download a succeeded export's rendered file",
    description=(
        "Serve the rendered file for an export job in status "
        "``succeeded``. Accepts a signed token in the ``token`` query "
        "parameter (preferred for browsers and email clients), or a "
        "JWT bearer credential, or an API key whose scopes include "
        "``export:read``. Returns 404 ``export_not_ready`` for "
        "non-succeeded jobs and 410 ``export_expired`` once the file "
        "has been swept by the retention task."
    ),
    responses={
        200: {
            "description": (
                "Streamed file response with the format-appropriate "
                "media type."
            ),
            "content": {
                "text/csv; charset=utf-8": {
                    "example": (
                        "response_id,respondent_id,submitted_at,q1\n"
                        "r-001,rcp-01,2026-04-12T08:30:00Z,5\n"
                    )
                },
                (
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ): {},
                "application/json": {},
                "application/octet-stream": {},
            },
        },
    },
)
async def download_export_job(
    job_id: str,
    request: Request,
    token: Optional[str] = Query(
        default=None,
        description=(
            "Signed download token issued by ``GET /{job_id}``. "
            "Required for browser / email-client downloads; omit when "
            "authenticating via JWT or API key."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Serve the rendered file for one export job.

    Resolves the caller via :func:`_resolve_download_caller`, loads the
    job by primary key, and streams the artifact from disk via
    :class:`FileResponse`. Returns:

    * 401 ``invalid_download_token`` when a token was supplied but
      failed verification.
    * 401 ``auth_required`` when no token was supplied and no valid
      credential could be resolved.
    * 403 ``insufficient_scope`` when an API key was resolved but
      lacks ``export:read``.
    * 404 ``export_job_not_found`` when the job is unknown or owned
      by a different user.
    * 404 ``export_not_ready`` when the job exists but is not in
      status ``succeeded`` (e.g. still ``queued`` / ``running``, or
      terminal in ``failed`` / ``expired``).
    * 410 ``export_expired`` when the job is ``succeeded`` but the
      on-disk artifact has been swept by the retention task or is
      otherwise missing — the row records succeeded state but the
      file no longer exists.

    Args:
        job_id: The id of the export job from the URL path.
        request: Inbound FastAPI request, forwarded to
            :func:`_resolve_download_caller` for credential parsing.
        token: Optional signed download token.
        db: Async database session.

    Returns:
        A :class:`FileResponse` carrying the rendered artifact with
        a format-appropriate ``Content-Type`` and a download
        ``filename`` of the form ``export.<format>``.

    Raises:
        HTTPException: As enumerated above.
    """
    user_id = await _resolve_download_caller(
        request=request, job_id=job_id, token=token, db=db
    )

    row = await db.get(ExportJob, job_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "export_job_not_found"},
        )

    if row.status != "succeeded":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "export_not_ready", "status": row.status},
        )

    if not row.storage_path or not Path(row.storage_path).exists():
        # The retention sweeper transitions ``succeeded`` to ``expired``
        # only after deleting the on-disk artifact; if we observe
        # ``succeeded`` but the file is gone, the row is mid-sweep or
        # the file was removed out-of-band. Either way the spec-correct
        # response is 410 Gone with a stable machine code.
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error": "export_expired"},
        )

    media_type = _MEDIA_TYPES.get(row.format, "application/octet-stream")
    return FileResponse(
        path=row.storage_path,
        media_type=media_type,
        filename=f"export.{row.format}",
    )

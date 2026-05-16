"""Export materialization worker — async multi-format survey-data export.

This module implements Component 7 of the API Open Platform design: the
Celery task ``materialize_export`` that consumes the ``exports`` queue
and drives one :class:`~app.models.export_job.ExportJob` through the
state machine ``queued → running → {succeeded, failed}``.

It also exposes the retention-sweeper task ``sweep_expired_exports``
that drives the ``succeeded → expired`` transition. The sweeper is
intended to run on Celery beat hourly, scans rows where
``status='succeeded' AND expires_at < now()``, deletes the on-disk
artifact, transitions the row to ``expired``, and emits a single
``export.job.expired`` audit row per swept job. The retention window is
read from :attr:`Settings.export_retention_hours` (default 168 hours
= 7 days) at job-success time and stored on the row as ``expires_at``,
so the sweeper makes its decision off a single column comparison.

Worker concurrency hints (set via the worker CLI, not on the app object)::

    celery -A app.tasks worker --queues=exports \\
        --concurrency=2 --max-tasks-per-child=50

Two concurrent materializations per worker is a balance between CPU /
memory pressure and worker count:

* XLSX with thousands of rows is memory-heavy because ``openpyxl`` holds
  the whole workbook in memory before writing.
* SAV and SAS7BDAT via ``pyreadstat`` have a known long-running memory
  growth issue.

The ``--max-tasks-per-child=50`` recycle bound caps process RSS so a
long-lived worker does not OOM.

Atomic write contract (Req 5.9):
    The producer writes to ``<output_path>.tmp`` inside the per-job
    storage directory. On success the worker calls
    ``os.replace(temp, final)`` so observers never see a partial output
    at the canonical path. On any exception the temp file is unlinked
    before the row transitions to ``failed``, so no partial output is
    retained on disk after a failed run.

Three-session pattern:
    The async body opens three short-lived :class:`AsyncSession` scopes
    so the long materialization step (file I/O for potentially
    multi-megabyte exports) does not hold a database transaction open:

    1. Session 1: load the job, validate format, transition to
       ``running``, commit.
    2. Session 2: load the survey and stream responses in id order
       (read-only).
    3. Session 3: re-load the job, write the terminal state plus the
       single audit row, commit.

Audit emission:
    Both materialization terminal transitions emit exactly one audit
    row with action ``export.job.succeeded`` or ``export.job.failed``
    and ``user_id`` set to the job owner. The ``details`` JSONB carries
    ``survey_id``, ``format``, ``byte_size`` (success only), and
    ``error_message`` (failure only) so a compliance reviewer can
    reconstruct the run without joining ``export_jobs``. The retention
    sweeper emits one ``export.job.expired`` audit row per swept job
    with ``survey_id``, ``format``, and the ``byte_size`` recorded at
    success time (the artifact itself is gone by the time the audit row
    is written).

Beat sweeper (operator hook):
    :func:`sweep_expired_exports` scans for ``succeeded`` rows whose
    ``expires_at`` is in the past, removes their on-disk artifacts, and
    transitions them to ``expired``. It is intended to run on Celery
    beat hourly. The wiring lives in operations / deployment config and
    is intentionally not added here (out of scope for this task).
    Recommended schedule for ``celery beat``::

        beat_schedule = {
            "exports-sweep-expired": {
                "task": "app.tasks.export_tasks.sweep_expired_exports",
                "schedule": 3600.0,  # 1 hour
                "options": {"queue": "exports"},
            },
        }

Reference: design.md §Component 7 + §"Export job state machine";
Requirements 5.4, 5.9, 5.10, 5.12.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from sqlalchemy import select

from . import celery_app
from ..config import settings
from ..core.audit import log_audit
from ..database import async_session
from ..services.export_formats import SUPPORTED_FORMATS

logger = logging.getLogger(__name__)


# ── Module constants ──────────────────────────────────────────────────

#: Maximum length stored in :attr:`ExportJob.error_message`. The column
#: itself is ``Text`` and accepts arbitrary length, but the listing UI
#: and audit ``details`` are bounded by this 1000-char convention used
#: elsewhere in the platform (see also ``WebhookDelivery.last_error``).
_ERROR_MESSAGE_MAX_CHARS: int = 1000

#: Mapping from export format identifier to on-disk file extension. SAV
#: and SAS7BDAT keep their bespoke extensions because downstream stats
#: tooling (SPSS, SAS) recognizes those magic suffixes.
_FORMAT_EXTENSION: dict = {
    "csv": "csv",
    "xlsx": "xlsx",
    "json": "json",
    "sav": "sav",
    "sas7bdat": "sas7bdat",
}


# ── Public Celery task ────────────────────────────────────────────────


@celery_app.task(name="app.tasks.export_tasks.materialize_export")
def materialize_export(job_id: str) -> None:
    """Materialize one export job and advance its row state.

    Synchronous Celery wrapper around :func:`_async_materialize_export`.
    The async body is run inside a fresh ``asyncio.run`` event loop on
    every invocation so each materialization owns its own database
    sessions and its own temp-file lifecycle. The task is idempotent on
    a per-row basis: if the row is already in a terminal state when the
    task runs (for example because a duplicate was enqueued), the body
    returns without doing any work.

    Args:
        job_id: UUID string of the
            :class:`~app.models.export_job.ExportJob` row to materialize.
    """
    asyncio.run(_async_materialize_export(job_id))


# ── Async body ────────────────────────────────────────────────────────


async def _async_materialize_export(job_id: str) -> None:
    """Async body: drive one ExportJob through queued → running → terminal.

    Opens three short-lived sessions (see module docstring §"Three-session
    pattern"). The long materialization step runs between sessions 2 and
    3 with no open transaction. On any exception during materialization
    the temp file is unlinked before session 3 writes the failed
    terminal state, so Req 5.9 (no partial output retained) holds
    structurally.

    Args:
        job_id: UUID string of the export job row to materialize.
    """
    # Local imports keep the Celery task module importable even when the
    # worker process boots before the ORM models module is fully loaded.
    from ..models.export_job import ExportJob
    from ..models.survey import Survey
    from ..models.survey_response import SurveyResponse

    # ── Session 1: validate and transition to running ───────────────
    prep = await _prepare_running(job_id)
    if prep is None:
        # Either the job is missing, already terminal, or rejected
        # outright (unsupported format / missing survey). Any audit
        # write and final state has already been committed inside
        # :func:`_prepare_running`.
        return
    survey_id, user_id, fmt = prep

    # ── Session 2: load survey + responses in id order (read-only) ──
    async with async_session() as db:
        survey = await db.get(Survey, survey_id)
        if survey is None:
            # Survey deleted between sessions 1 and 2 (rare edge case
            # because the FK has ON DELETE CASCADE on export_jobs, so
            # this only fires under a dirty manual delete). Mark the
            # row failed and return.
            await _terminate(
                job_id=job_id,
                user_id=user_id,
                survey_id=survey_id,
                fmt=fmt,
                output_path=None,
                byte_size=None,
                error_text="survey_not_found",
            )
            return

        stmt = (
            select(SurveyResponse)
            .where(SurveyResponse.survey_id == survey_id)
            .order_by(SurveyResponse.id)
        )
        result = await db.execute(stmt)
        responses: List[Any] = list(result.scalars().all())

    # ── Materialize outside any open transaction ────────────────────
    output_path: Optional[Path] = None
    temp_path: Optional[Path] = None
    error_text: Optional[str] = None
    byte_size: Optional[int] = None

    try:
        ext = _FORMAT_EXTENSION.get(fmt, fmt)
        storage_root = Path(settings.export_storage_root)
        job_dir = storage_root / str(user_id) / str(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)

        filename = f"export.{ext}"
        output_path = job_dir / filename
        temp_path = job_dir / f"{filename}.tmp"

        # Dispatch to the format-specific producer. SAV / SAS7BDAT
        # imports are inside the conditional branches so a worker
        # without ``pyreadstat`` does not pay the import cost (and does
        # not crash at module load if the native library is missing).
        if fmt == "csv":
            from ..services.export_formats import write_csv
            write_csv(survey, responses, temp_path)
        elif fmt == "xlsx":
            from ..services.export_formats import write_xlsx
            write_xlsx(survey, responses, temp_path)
        elif fmt == "json":
            from ..services.export_formats import write_json
            write_json(survey, responses, temp_path)
        elif fmt == "sav":
            from ..services.export_formats.sav_producer import write_sav
            write_sav(survey, responses, temp_path)
        elif fmt == "sas7bdat":
            from ..services.export_formats.sas_producer import write_sas7bdat
            write_sas7bdat(survey, responses, temp_path)
        else:
            # Defensive: format support was validated in session 1, so
            # this branch is unreachable under normal operation.
            raise ValueError(f"format_unsupported: {fmt}")

        # Atomic publish: replace is atomic on POSIX when source and
        # destination live on the same filesystem, which they do by
        # construction (both are inside ``job_dir``).
        os.replace(str(temp_path), str(output_path))
        byte_size = output_path.stat().st_size
        # Clear ``temp_path`` so the failure cleanup branch below does
        # not try to unlink a path that was just renamed.
        temp_path = None

    except Exception as exc:  # noqa: BLE001 — terminal failure backstop
        error_text = _truncate(f"{type(exc).__name__}: {exc}")
        logger.exception(
            "Export materialization failed for job %s (format=%s)",
            job_id,
            fmt,
        )
        # Cleanup partial output before the row transitions to failed
        # so Req 5.9 (no partial output retained) holds.
        if temp_path is not None:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                logger.exception(
                    "Failed to unlink temp file %s during error cleanup",
                    temp_path,
                )

    # ── Session 3: write terminal state + audit, commit ─────────────
    await _terminate(
        job_id=job_id,
        user_id=user_id,
        survey_id=survey_id,
        fmt=fmt,
        output_path=output_path if error_text is None else None,
        byte_size=byte_size if error_text is None else None,
        error_text=error_text,
    )


# ── Internal helpers ──────────────────────────────────────────────────


async def _prepare_running(
    job_id: str,
) -> Optional[Tuple[str, str, str]]:
    """Session 1: validate the job and transition queued → running.

    Loads the row, checks idempotency (already-terminal jobs are
    skipped), validates that the requested format is supported in this
    worker's runtime environment, stamps ``started_at``, and commits.
    On unsupported format or missing survey it transitions the row
    directly to ``failed`` (with an audit row) and returns ``None`` so
    the caller can stop.

    Args:
        job_id: UUID string of the export job row.

    Returns:
        ``(survey_id, user_id, format)`` triple if the row is now in
        ``running`` state and materialization should proceed; ``None``
        if the caller should stop (idempotent skip, or terminal failure
        already recorded).
    """
    from ..models.export_job import ExportJob
    from ..models.survey import Survey

    async with async_session() as db:
        job = await db.get(ExportJob, job_id)
        if job is None:
            logger.warning("ExportJob %s not found; abandoning task", job_id)
            return None

        if job.status in ("running", "succeeded", "failed", "expired"):
            # Idempotent skip. ``running`` shows up if a duplicate Celery
            # task fires while the original is mid-flight; the original
            # owns the row.
            return None

        # Validate format support in this worker's runtime. The route
        # layer also rejects unsupported formats at create time, so this
        # is a defensive double-check for the case where the worker's
        # ``pyreadstat`` availability differs from the API's.
        if job.format not in SUPPORTED_FORMATS:
            error_text = _truncate(f"format_unsupported: {job.format}")
            now = datetime.now(timezone.utc)
            job.status = "failed"
            job.error_message = error_text
            job.completed_at = now
            await _emit_audit(
                db,
                action="export.job.failed",
                user_id=job.user_id,
                job_id=job.id,
                survey_id=job.survey_id,
                fmt=job.format,
                byte_size=None,
                error_text=error_text,
            )
            await db.commit()
            return None

        # Confirm the survey exists. ``ExportJob.survey_id`` has
        # ON DELETE CASCADE on ``surveys.id`` so a deleted survey
        # normally takes the export row with it; this branch covers
        # the rare race where a manual delete bypassed the cascade.
        survey = await db.get(Survey, job.survey_id)
        if survey is None:
            error_text = "survey_not_found"
            now = datetime.now(timezone.utc)
            job.status = "failed"
            job.error_message = error_text
            job.completed_at = now
            await _emit_audit(
                db,
                action="export.job.failed",
                user_id=job.user_id,
                job_id=job.id,
                survey_id=job.survey_id,
                fmt=job.format,
                byte_size=None,
                error_text=error_text,
            )
            await db.commit()
            return None

        # Capture before commit — ORM attributes remain accessible after
        # the session closes, but pulling them into locals avoids any
        # ambiguity about implicit refresh.
        survey_id = job.survey_id
        user_id = job.user_id
        fmt = job.format

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

    return (survey_id, user_id, fmt)


async def _terminate(
    *,
    job_id: str,
    user_id: str,
    survey_id: str,
    fmt: str,
    output_path: Optional[Path],
    byte_size: Optional[int],
    error_text: Optional[str],
) -> None:
    """Session 3: write the terminal state plus the audit row.

    Re-loads the job in a fresh session, applies the terminal
    transition (``succeeded`` if ``error_text`` is ``None``, otherwise
    ``failed``), populates the success-only or failure-only columns,
    emits a single audit row, and commits.

    Args:
        job_id: UUID string of the export job row.
        user_id: UUID string of the job owner (denormalized so the
            audit emission does not need to re-read the row).
        survey_id: UUID string of the source survey (for audit details).
        fmt: Export format (for audit details).
        output_path: Final on-disk path of the materialized artifact.
            ``None`` on failure.
        byte_size: Size in bytes of the materialized artifact. ``None``
            on failure.
        error_text: Truncated error description (already passed through
            :func:`_truncate`). ``None`` on success.
    """
    from ..models.export_job import ExportJob

    async with async_session() as db:
        job = await db.get(ExportJob, job_id)
        if job is None:
            # Row was deleted between sessions 2 and 3. Nothing to
            # update; the audit row would have no resource to point
            # at, so skip emission.
            logger.warning(
                "ExportJob %s vanished before terminal transition", job_id
            )
            return

        now = datetime.now(timezone.utc)
        if error_text is not None:
            job.status = "failed"
            job.error_message = error_text
            job.completed_at = now
            action = "export.job.failed"
        else:
            job.status = "succeeded"
            job.storage_path = str(output_path) if output_path else None
            job.byte_size = byte_size
            job.completed_at = now
            job.expires_at = now + timedelta(
                hours=settings.export_retention_hours
            )
            action = "export.job.succeeded"

        await _emit_audit(
            db,
            action=action,
            user_id=user_id,
            job_id=job_id,
            survey_id=survey_id,
            fmt=fmt,
            byte_size=byte_size,
            error_text=error_text,
        )
        await db.commit()


async def _emit_audit(
    db,
    *,
    action: str,
    user_id: Optional[str],
    job_id: str,
    survey_id: str,
    fmt: str,
    byte_size: Optional[int],
    error_text: Optional[str],
) -> None:
    """Emit one audit row for an export terminal transition.

    Wraps :func:`app.core.audit.log_audit` with the canonical
    ``details`` shape used by the export subsystem so the success and
    failure paths produce uniform records. The caller is responsible
    for committing the transaction.

    Args:
        db: Active async database session.
        action: Either ``export.job.succeeded`` or
            ``export.job.failed``.
        user_id: UUID of the job owner. May be ``None`` only in the
            (currently unreachable) case where the row's ``user_id``
            is itself null.
        job_id: UUID of the export job row, used as the audit row's
            ``resource_id``.
        survey_id: UUID of the source survey (carried in ``details``).
        fmt: Export format (carried in ``details``).
        byte_size: Size in bytes on success; ``None`` on failure.
        error_text: Truncated error description on failure; ``None``
            on success.
    """
    details = {
        "job_id": job_id,
        "survey_id": survey_id,
        "format": fmt,
    }
    if byte_size is not None:
        details["byte_size"] = byte_size
    if error_text is not None:
        details["error_message"] = error_text

    await log_audit(
        db,
        action=action,
        user_id=user_id,
        resource_type="export_job",
        resource_id=job_id,
        details=details,
    )


def _truncate(text: str) -> str:
    """Truncate a string to fit ``ExportJob.error_message`` conventions.

    The model column is ``Text`` and accepts arbitrary length, but the
    application contract caps error descriptions at 1000 characters so
    a stack trace cannot bloat the row arbitrarily (Req 5.10).

    Args:
        text: Possibly long error description.

    Returns:
        ``text`` truncated to at most :data:`_ERROR_MESSAGE_MAX_CHARS`.
    """
    if len(text) <= _ERROR_MESSAGE_MAX_CHARS:
        return text
    return text[:_ERROR_MESSAGE_MAX_CHARS]


# ── Retention sweeper ────────────────────────────────────────────────


@celery_app.task(name="app.tasks.export_tasks.sweep_expired_exports")
def sweep_expired_exports() -> None:
    """Sweep succeeded exports past their retention deadline.

    Synchronous Celery wrapper around
    :func:`_async_sweep_expired_exports`. Designed to run on Celery beat
    hourly so that succeeded exports past their ``expires_at`` are
    transitioned to ``expired`` with their on-disk artifact removed.

    Recommended ``celery beat`` schedule entry::

        beat_schedule = {
            "exports-sweep-expired": {
                "task": "app.tasks.export_tasks.sweep_expired_exports",
                "schedule": 3600.0,  # 1 hour
                "options": {"queue": "exports"},
            },
        }
    """
    asyncio.run(_async_sweep_expired_exports())


async def _async_sweep_expired_exports() -> None:
    """Find and expire succeeded exports past their retention deadline.

    Reads candidate row ids in a short read-only transaction, then
    processes each candidate independently so a transient error on one
    row does not abort the rest of the batch. For each candidate row:

    1. The on-disk artifact is unlinked (best effort; a missing file is
       not an error because manual cleanup may have already removed it).
    2. The row's ``status`` transitions from ``succeeded`` to
       ``expired``; ``storage_path`` and ``byte_size`` are cleared so
       downstream consumers cannot mistakenly try to serve a file that
       no longer exists.
    3. A single ``export.job.expired`` audit row is emitted carrying
       the original ``survey_id``, ``format``, and ``byte_size`` so a
       compliance reviewer can reconstruct what was held without
       joining ``export_jobs``.

    The original ``completed_at`` (the timestamp at which materialization
    finished) is left unchanged. The expiration timestamp is implicit
    from ``status='expired'`` plus the retention column ``expires_at``.
    """
    from ..models.export_job import ExportJob

    now = datetime.now(timezone.utc)

    # Read candidates in a short read-only transaction. Pulling only
    # the fields needed downstream (ids and the per-row data carried
    # into the audit row) avoids holding ORM-attached objects across
    # session boundaries.
    async with async_session() as db:
        stmt = select(ExportJob).where(
            ExportJob.status == "succeeded",
            ExportJob.expires_at.is_not(None),
            ExportJob.expires_at < now,
        )
        result = await db.execute(stmt)
        candidates = list(result.scalars().all())
        snapshot = [
            {
                "id": j.id,
                "user_id": j.user_id,
                "survey_id": j.survey_id,
                "format": j.format,
                "storage_path": j.storage_path,
                "byte_size": j.byte_size,
            }
            for j in candidates
        ]

    if not snapshot:
        return

    for snap in snapshot:
        try:
            await _expire_one(snap)
        except Exception:  # noqa: BLE001 — per-row backstop
            logger.exception(
                "Retention sweep failed for export %s; "
                "next tick will retry",
                snap["id"],
            )


async def _expire_one(snap: dict) -> None:
    """Expire one export job: unlink artifact, update row, emit audit.

    The on-disk unlink is performed before the database update so that
    if the unlink raises, the row is left in ``succeeded`` and the next
    sweeper tick will retry; this keeps the invariant that
    ``status='expired'`` implies the artifact is gone.

    Args:
        snap: Snapshot of the export job's pre-expire fields captured
            in :func:`_async_sweep_expired_exports`. Must contain
            ``id``, ``user_id``, ``survey_id``, ``format``,
            ``storage_path``, and ``byte_size``.
    """
    from ..models.export_job import ExportJob

    storage_path = snap.get("storage_path")
    if storage_path:
        try:
            p = Path(storage_path)
            if p.exists():
                p.unlink()
            # Best-effort: remove the per-job directory if now empty.
            # ``rmdir`` raises ``OSError`` if the directory is not
            # empty (e.g., another concurrent download path created a
            # sibling), which is fine — leave it for the next sweep.
            try:
                p.parent.rmdir()
            except OSError:
                pass
        except Exception:  # noqa: BLE001 — best-effort unlink
            logger.exception(
                "Failed to unlink %s during retention sweep; "
                "leaving row as succeeded for retry",
                storage_path,
            )
            # Do not advance the row state if we could not delete the
            # file. Otherwise ``status='expired'`` would lie.
            return

    async with async_session() as db:
        job = await db.get(ExportJob, snap["id"])
        if job is None:
            # Row was deleted between snapshot and update. Nothing to
            # do; the file (if any) is already gone above.
            return
        if job.status != "succeeded":
            # Concurrent modification: another sweep tick won, or the
            # row was manually transitioned. The terminal-state-wins
            # rule applies: skip.
            return

        job.status = "expired"
        job.storage_path = None
        job.byte_size = None

        await log_audit(
            db,
            action="export.job.expired",
            user_id=snap["user_id"],
            resource_type="export_job",
            resource_id=snap["id"],
            details={
                "job_id": snap["id"],
                "survey_id": snap["survey_id"],
                "format": snap["format"],
                "byte_size": snap["byte_size"],
            },
        )
        await db.commit()

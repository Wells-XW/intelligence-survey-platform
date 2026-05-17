"""ExportJob ORM model — asynchronous survey-data materialization requests."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class ExportJob(Base):
    """A single asynchronous data-export request against one survey.

    Each row represents one user's request to materialize one survey's
    response set into one supported file format. The row tracks the
    request through the state machine described in design.md
    §"Export job state machine":

    * ``queued`` — The request has been accepted and persisted, but the
      worker has not yet started materialization. ``started_at`` is
      ``None``.
    * ``running`` — The worker has dequeued the row and begun writing
      output. ``started_at`` is set; ``completed_at`` is ``None``.
    * ``succeeded`` — Materialization finished without error.
      ``completed_at``, ``storage_path``, ``byte_size``, and
      ``expires_at`` are populated. The hourly retention sweeper later
      transitions this row to ``expired`` when ``expires_at`` is
      reached.
    * ``failed`` — Materialization raised an exception.
      ``completed_at`` and ``error_message`` are set. The application
      layer truncates ``error_message`` to 1000 characters before
      insert so a stack trace cannot bloat the row arbitrarily.
    * ``expired`` — Terminal state reached only from ``succeeded`` by
      the retention sweeper after ``expires_at`` has passed. The
      ``storage_path`` artifact has been deleted from object storage,
      but the row is retained for audit and listing purposes.

    Format support:
        ``csv`` / ``xlsx`` / ``json`` are mandatory and always
        available. ``sav`` (SPSS) and ``xpt`` (SAS Transport) are
        conditional on the ``pyreadstat`` optional dependency being
        importable at worker startup; if it is not, requests for those
        formats are rejected at the API layer before a row is created.

    SAS format note:
        The platform writes SAS Transport (``.xpt``) rather than
        ``.sas7bdat``. The pyreadstat library exposes only a SAS7BDAT
        *reader*; XPORT is the supported write path and downstream
        SAS users import the file with ``PROC CIMPORT``.

    The ``options`` JSONB column is reserved for future filtering knobs
    (date ranges, column subsets, response-status filters, locale
    overrides, etc.) that are not in the current scope but should not
    require a schema migration to land. Today it is always ``None`` or
    an empty object.

    Attributes:
        id: Primary key, UUID stored as a string.
        user_id: Foreign key to ``users.id`` with ``ON DELETE CASCADE``;
            the requesting user.
        survey_id: Foreign key to ``surveys.id`` with
            ``ON DELETE CASCADE``; the survey whose responses are
            being materialized.
        format: Output format identifier; one of ``csv`` / ``xlsx`` /
            ``json`` / ``sav`` / ``xpt``.
        status: Current state-machine position; one of ``queued`` /
            ``running`` / ``succeeded`` / ``failed`` / ``expired``.
        options: Reserved JSONB map for future materialization knobs;
            currently unused.
        storage_path: Object-storage path of the rendered artifact;
            populated only on transition to ``succeeded``.
        byte_size: Size in bytes of the rendered artifact; populated
            only on transition to ``succeeded``.
        error_message: Truncated (1000 chars) failure description;
            populated only on transition to ``failed``.
        created_at: Insert timestamp.
        started_at: Timestamp set when the worker dequeues the row and
            transitions it to ``running``.
        completed_at: Timestamp set when the row reaches ``succeeded``
            or ``failed``.
        expires_at: Retention deadline for the rendered artifact;
            populated only on transition to ``succeeded``. The hourly
            sweeper uses this to drive the ``succeeded`` → ``expired``
            transition.
        user: SQLAlchemy relationship to the requesting :class:`User`
            (unidirectional; no back-population).
        survey: SQLAlchemy relationship to the source :class:`Survey`
            (unidirectional; no back-population).
    """

    __tablename__ = "export_jobs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    survey_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=False,
    )
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    options: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    byte_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships (unidirectional; User and Survey do not back-populate).
    user = relationship("User")
    survey = relationship("Survey")

    def __repr__(self) -> str:
        return (
            f"<ExportJob(id={self.id}, survey_id={self.survey_id}, "
            f"format={self.format!r}, status={self.status!r})>"
        )

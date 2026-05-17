"""Add export_jobs table.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-16

This migration introduces the asynchronous data-export subsystem for
T15 ("API Open Platform and Export Enhancement"):

    - Creates the ``export_jobs`` table per design.md
      §"Data Models 0010". Each row represents a single materialization
      request from a user against one survey in one supported format
      (``csv`` / ``xlsx`` / ``json`` / ``sav`` / ``xpt``) and
      tracks that request through the queued / running / succeeded /
      failed / expired state machine described in design.md
      §"Export job state machine".
    - The ``options`` JSONB column is reserved for future
      materialization knobs (date range filters, column subsets, etc.)
      that are not in the current scope but should not require another
      schema migration to land.
    - ``storage_path`` and ``byte_size`` are populated only on a
      successful transition to ``succeeded``; ``error_message`` is
      populated only on a transition to ``failed`` and is truncated by
      the application layer to 1000 characters before insert.
    - Three indices match the three known access patterns:

        1. Composite ``(user_id, created_at DESC)`` to power the
           caller's "list my jobs" endpoint, which paginates newest
           first inside a single user's history.
        2. Partial ``(status) WHERE status IN ('queued','running')`` so
           the worker dequeue path scans an index proportional to the
           number of in-flight jobs rather than total job history.
        3. Partial ``(expires_at) WHERE status = 'succeeded'`` so the
           hourly retention sweeper that transitions
           ``succeeded`` → ``expired`` can find the candidate rows
           without scanning historical failures or already-expired
           rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create the ``export_jobs`` table and its three access-pattern indices.

    The table is created first; the three indices are created
    afterwards so that the partial-index predicates are parsed in a
    context where the ``status`` and ``expires_at`` columns are already
    known to Postgres.
    """
    # 1. export_jobs: one row per materialization request.
    op.create_table(
        "export_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "survey_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("surveys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("storage_path", sa.String(500), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Composite index for the caller's "list my jobs" endpoint
    #    (paginated DESC by created_at within a single user's history).
    op.create_index(
        "ix_export_jobs_user_created",
        "export_jobs",
        ["user_id", sa.text("created_at DESC")],
    )

    # 3. Partial index for the worker dequeue path. Only rows currently
    #    queued or running are interesting; terminal-state rows
    #    (succeeded / failed / expired) do not need to be scanned.
    op.create_index(
        "ix_export_jobs_status_active",
        "export_jobs",
        ["status"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    # 4. Partial index for the hourly retention sweeper. Only succeeded
    #    rows have a meaningful ``expires_at`` to compare against;
    #    failed and expired rows are excluded so the sweeper's index
    #    scan is proportional to the count of live successful exports.
    op.create_index(
        "ix_export_jobs_expires_succeeded",
        "export_jobs",
        ["expires_at"],
        postgresql_where=sa.text("status = 'succeeded'"),
    )


def downgrade() -> None:
    """Drop the ``export_jobs`` table.

    Indices on a table are dropped automatically when the table is
    dropped, but the explicit ``op.drop_index`` calls below mirror the
    structure of ``upgrade()`` and make the migration's intent
    self-documenting. They are dropped in reverse order of creation.
    """
    op.drop_index(
        "ix_export_jobs_expires_succeeded",
        table_name="export_jobs",
    )
    op.drop_index(
        "ix_export_jobs_status_active",
        table_name="export_jobs",
    )
    op.drop_index(
        "ix_export_jobs_user_created",
        table_name="export_jobs",
    )
    op.drop_table("export_jobs")

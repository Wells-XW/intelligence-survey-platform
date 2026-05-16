"""Add webhook_subscriptions and webhook_deliveries tables.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-16

This migration introduces the webhook subsystem for T15 ("API Open
Platform and Export Enhancement"):

    - Creates the ``webhook_subscriptions`` table per design.md
      §"Data Models 0009". Each subscription stores the SHA-256 hash of
      its current signing secret in ``signing_secret_hash`` and an
      optional ``previous_secret_hash`` that is populated only during
      the rotation invalidation window described in Req 3 AC5. The
      plaintext secret is shown exactly once at create or rotate time
      and never persisted. ``survey_id`` is nullable to express the
      "all surveys the owner can see" subscription shape; the FK still
      cascades on survey deletion.
    - Creates the ``webhook_deliveries`` table per design.md
      §"Data Models 0009". The row's ``id`` doubles as the value of the
      outbound ``X-Webhook-Delivery`` HTTP header so receivers can
      dedupe retries. The ``status`` column is the canonical state for
      the delivery state machine (``pending`` / ``retrying`` /
      ``succeeded`` / ``failed_permanent``); ``attempt_count`` and
      ``next_attempt_at`` are read by the Celery worker rather than by
      Celery's own retry counter so a worker restart cannot lose state.
    - Adds two access-pattern indices on ``webhook_deliveries``: a
      composite ``(subscription_id, created_at DESC)`` for the
      delivery-history endpoint, and a partial index on ``status`` that
      only materializes rows in ``retrying`` so the reconciler that
      sweeps pending-retry deliveries scans an index whose size is
      proportional to in-flight retries rather than total history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create the ``webhook_subscriptions`` and ``webhook_deliveries`` tables.

    The two tables are created in dependency order: subscriptions
    first, then deliveries (which carries an FK to subscriptions). The
    delivery indices are created after the table so the partial-index
    predicate is parsed in a context where the ``status`` column is
    already known.
    """
    # 1. webhook_subscriptions: one row per (owner, target URL, event set).
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "survey_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("surveys.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("target_url", sa.String(2048), nullable=False),
        sa.Column("event_types", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("signing_secret_hash", sa.String(64), nullable=False),
        sa.Column("previous_secret_hash", sa.String(64), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_status", sa.String(20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 2. webhook_deliveries: one row per delivery attempt sequence.
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_response_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 3. Composite index for the delivery-history endpoint
    #    (paginated DESC by created_at within a subscription).
    op.create_index(
        "ix_webhook_deliveries_subscription_created",
        "webhook_deliveries",
        ["subscription_id", sa.text("created_at DESC")],
    )

    # 4. Partial index for the retry reconciler. Only rows currently in
    #    ``retrying`` are interesting; succeeded / failed_permanent rows
    #    are terminal and do not need to be scanned.
    op.create_index(
        "ix_webhook_deliveries_status_retrying",
        "webhook_deliveries",
        ["status"],
        postgresql_where=sa.text("status = 'retrying'"),
    )


def downgrade() -> None:
    """Drop the ``webhook_deliveries`` and ``webhook_subscriptions`` tables.

    Tables are dropped in reverse dependency order: deliveries first
    (since it FKs subscriptions), then subscriptions. Indices on a
    table are dropped automatically when the table is dropped, but the
    explicit ``op.drop_index`` calls below make the migration's intent
    explicit and keep ``downgrade()`` readable as a mirror of
    ``upgrade()``.
    """
    op.drop_index(
        "ix_webhook_deliveries_status_retrying",
        table_name="webhook_deliveries",
    )
    op.drop_index(
        "ix_webhook_deliveries_subscription_created",
        table_name="webhook_deliveries",
    )
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_subscriptions")

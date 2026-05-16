"""Add API platform composite indices.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-16

This migration introduces two composite indices that accelerate hot
read paths added by T15 ("API Open Platform and Export Enhancement").
Both indices target tables that already exist (``audit_logs`` from
``0001_initial_auth`` and ``webhook_deliveries`` from
``0009_add_webhook_subscriptions_and_deliveries``); no new tables or
columns are introduced here.

    1. ``ix_audit_logs_action_created`` on
       ``audit_logs(action, created_at DESC)`` accelerates the
       admin-facing audit-logs listing endpoint added in Task 15.1.
       That endpoint filters by ``action`` (e.g. ``api_key.revoke``,
       ``webhook.delivery.failed``) and paginates newest-first by
       ``created_at``. The pre-existing single-column indices
       ``ix_audit_logs_action`` and ``ix_audit_logs_created_at``
       (created in ``0001_initial_auth``) cannot serve this composite
       access pattern without bitmap-merging, which materially
       degrades latency once ``audit_logs`` accumulates retention-window
       volume. The new composite leaves the original two indices in
       place because they still serve other queries (resource-scoped
       lookups by action alone, time-range scans without action
       filter).
    2. ``ix_webhook_deliveries_subscription_status`` on
       ``webhook_deliveries(subscription_id, status)`` accelerates the
       cache-invalidation queries that maintain
       ``webhook_subscriptions.last_delivery_status``. Those queries
       look up the most recent terminal-state delivery per subscription
       (``status IN ('succeeded', 'failed_permanent')``), which the
       existing ``ix_webhook_deliveries_subscription_created`` index
       (subscription_id, created_at DESC) created in ``0009`` cannot
       satisfy without a separate filter step. Keeping both indices is
       intentional: the ``0009`` index serves the chronological
       delivery-history endpoint, and this new index serves the
       status-cache write path. Postgres's index selector picks the
       cheaper of the two per query plan.

Validates: Requirements 7.7, 4.9.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create the two composite indices.

    Both indices are plain (non-partial) composites. The
    ``audit_logs`` index uses ``DESC`` on ``created_at`` so the
    admin-listing endpoint's ``ORDER BY created_at DESC`` is satisfied
    by an index scan rather than a separate sort step. The
    ``webhook_deliveries`` index uses default ascending order on
    ``status`` because the predicate is equality / ``IN`` rather than
    range, so direction is irrelevant for selection.
    """
    # 1. Composite for the admin audit-logs listing endpoint.
    op.create_index(
        "ix_audit_logs_action_created",
        "audit_logs",
        ["action", sa.text("created_at DESC")],
    )

    # 2. Composite for the last_delivery_status cache invalidation.
    op.create_index(
        "ix_webhook_deliveries_subscription_status",
        "webhook_deliveries",
        ["subscription_id", "status"],
    )


def downgrade() -> None:
    """Drop the two composite indices in reverse order of creation.

    Reverse-order drops are not strictly required for index removal
    (no dependency exists between the two), but they mirror the
    structure of ``upgrade()`` and keep the migration's intent
    self-documenting in line with ``0010_add_export_jobs.py``.
    """
    op.drop_index(
        "ix_webhook_deliveries_subscription_status",
        table_name="webhook_deliveries",
    )
    op.drop_index(
        "ix_audit_logs_action_created",
        table_name="audit_logs",
    )

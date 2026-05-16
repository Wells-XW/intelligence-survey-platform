"""Add api_keys table and users.is_admin flag.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-16

This migration introduces the API key lifecycle subsystem for T15
("API Open Platform and Export Enhancement"):

    - Adds ``users.is_admin`` (BOOLEAN NOT NULL DEFAULT false) so that the
      forthcoming admin endpoints and admin-only scopes (``admin:read``,
      ``admin:write``, ``audit:read``) can be gated by a single column on
      the existing users table.
    - Creates the ``api_keys`` table per design.md §"Data Models 0008".
      Every secret is stored only as a SHA-256 hash; the plaintext is
      shown exactly once at creation or rotation time. The ``key_prefix``
      column holds the first 11 characters of the plaintext (e.g.
      ``sk_live_ab``) and is uniquely indexed for O(1) auth lookup. A
      partial index on ``revoked_at`` accelerates listing of active keys
      by skipping revoked rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Add ``users.is_admin`` column and create the ``api_keys`` table.

    The ``is_admin`` column is added with a server-side default of
    ``false`` so existing rows backfill safely without a separate UPDATE.
    The ``api_keys`` table carries one partial index on ``revoked_at``
    that filters out revoked rows, speeding up the common
    "list active keys for user X" query path.
    """
    # 1. Extend users with the admin flag.
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 2. Create the api_keys table.
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "key_prefix",
            sa.String(11),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column("rate_limit_overrides", postgresql.JSONB(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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

    # 3. Partial index for fast active-key listing.
    op.create_index(
        "ix_api_keys_revoked_at_active",
        "api_keys",
        ["revoked_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    """Drop the ``api_keys`` table and remove ``users.is_admin``.

    Dropping the table also drops its associated indices (including the
    partial index created above), so they are not dropped explicitly.
    """
    op.drop_index("ix_api_keys_revoked_at_active", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_column("users", "is_admin")

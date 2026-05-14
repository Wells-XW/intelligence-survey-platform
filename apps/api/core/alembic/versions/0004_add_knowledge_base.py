"""Add knowledge_base tables: literature_references, knowledge_scales, knowledge_entries.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── literature_references ─────────────────────────────────────────
    op.create_table(
        "literature_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("external_source", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("authors", JSONB, nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("journal", sa.String(500), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("doi", sa.String(200), nullable=True, index=True),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("keywords", JSONB, nullable=True),
        sa.Column("raw_citation", sa.Text(), nullable=True),
        sa.Column("is_saved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "external_source", "external_id",
            name="uq_lit_ref_user_source_ext",
        ),
    )
    # Composite index for literature lookup
    op.create_index(
        "ix_lit_refs_external",
        "literature_references",
        ["external_source", "external_id"],
    )
    # Full-text search support via pg_trgm
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_lit_refs_title_trgm "
        "ON literature_references USING gin (title gin_trgm_ops)"
    )

    # ── knowledge_scales ──────────────────────────────────────────────
    op.create_table(
        "knowledge_scales",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("discipline", sa.String(50), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("items", JSONB, nullable=True),
        sa.Column("cronbach_alpha", sa.Float(), nullable=True),
        sa.Column("cronbach_alpha_history", JSONB, nullable=True),
        sa.Column("citations", JSONB, nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="zh"),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("external_source", sa.String(50), nullable=True),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_scales_discipline", "knowledge_scales", ["discipline"])
    op.create_index("ix_scales_language", "knowledge_scales", ["language"])

    # ── knowledge_entries ─────────────────────────────────────────────
    op.create_table(
        "knowledge_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("category", sa.String(50), nullable=False, index=True),
        sa.Column("content", JSONB, nullable=True),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="zh"),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_entries_category", "knowledge_entries", ["category"])


def downgrade() -> None:
    op.drop_table("knowledge_entries")
    op.drop_table("knowledge_scales")
    op.drop_table("literature_references")

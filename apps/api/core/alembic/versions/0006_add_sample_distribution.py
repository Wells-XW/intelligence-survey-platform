"""Add sample distribution tables: sample_groups, recipients, distributions, quotas.

Revision ID: 0006
Revises: 0005_add_compliance_checks
Create Date: 2026-05-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── sample_groups ──
    op.create_table(
        "sample_groups",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "survey_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("surveys.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("recipient_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # ── recipients ──
    op.create_table(
        "recipients",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "sample_group_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("sample_groups.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("external_id", sa.String(200), nullable=True, index=True),
        sa.Column("demographics", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("unique_token", sa.String(64), unique=True, nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_recipients_unique_token", "recipients", ["unique_token"], unique=True
    )

    # ── distributions ──
    op.create_table(
        "distributions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "survey_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("surveys.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "sample_group_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("sample_groups.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("subject_template", sa.Text, nullable=True),
        sa.Column("body_template", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("sent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("opened_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # ── quotas ──
    op.create_table(
        "quotas",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "survey_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("surveys.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("dimension", sa.String(50), nullable=False),
        sa.Column("target_count", sa.Integer, nullable=False),
        sa.Column("current_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("criteria", postgresql.JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    # Composite index for efficient active quota lookup during response submission
    op.create_index(
        "ix_quotas_survey_active",
        "quotas",
        ["survey_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_table("quotas")
    op.drop_table("distributions")
    op.drop_table("recipients")
    op.drop_table("sample_groups")

"""Add compliance_checks table for ethics & regulatory audit records.

Revision ID: 0005
Revises: 0004_add_knowledge_base
Create Date: 2026-05-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_checks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "survey_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("surveys.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("check_type", sa.String(50), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("findings", postgresql.JSONB, default=dict),
        sa.Column("suggestions", postgresql.JSONB, default=dict),
        sa.Column("risk_score", sa.Float, default=0.0),
        sa.Column("items_checked", sa.Integer, default=0),
        sa.Column("items_passed", sa.Integer, default=0),
        sa.Column("items_warning", sa.Integer, default=0),
        sa.Column("items_failed", sa.Integer, default=0),
        sa.Column(
            "checked_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("compliance_checks")
